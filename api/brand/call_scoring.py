"""Quality and technical score of every call, computed when it ends.

The same two grades as the calls of a test campaign: a quality score (the
analysis model reads the transcript and grades the agent 1-5 on understanding,
accuracy, concision, tone and resolution) and a technical score (latency
posts, voice fluency, tools and reliability graded against the Analysis
thresholds, ``api/brand/test_technical.py``). There is no scenario: the judge
grades the agent against its own configuration.

Stored on the run as ``annotations["oxee_score"]``. Test-campaign calls are
left out (their execution grades them) and so are calls without a
conversation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from statistics import mean
from typing import Any

from loguru import logger

from api.db import db_client

SCORE_KEY = "oxee_score"
SCORE_KEYS = ("understanding", "accuracy", "concision", "tone", "resolution")

QUALITY_PROMPT = """You review a call between a caller and a phone voice agent.
You receive the agent's configuration (nodes with their instructions,
transitions), the transcript with the agent's node for each reply and the tool
calls, the variables the agent extracted and how the call ended.

Grade the AGENT, not the caller, against what its configuration says it should
do:
- scores 1-5: understanding (got what the caller wanted), accuracy (correct
  information, no invention), concision (short replies fit for the phone), tone
  (polite, adapted to the caller), resolution (handled the request to its end,
  or routed it as configured);
- "resolved": did the caller get what they called for, as far as the agent is
  supposed to provide it?
- "summary": one sentence on the call;
- "issues": up to 3 short sentences on what the agent should do better (empty
  when nothing).
The transcript comes from speech recognition: small transcription errors are
normal; do not blame the agent for words the recognition got wrong.
Write in {language}. Answer only with JSON:
{"scores": {"understanding": int, "accuracy": int, "concision": int, "tone": int, "resolution": int},
 "resolved": bool, "summary": str, "issues": [str]}"""

LANGUAGE = "French"


def _skip(run: Any) -> str | None:
    from api.brand.db import SIM_RUN_PREFIX, TEST_RUN_PREFIX

    name = getattr(run, "name", "") or ""
    if name.startswith((TEST_RUN_PREFIX, SIM_RUN_PREFIX)):
        return "test call"
    return None


def quality_score(scores: dict) -> float | None:
    values = [scores[k] for k in SCORE_KEYS if isinstance(scores.get(k), int)]
    return round(mean(values), 2) if values else None


async def score_run(run_id: int, *, force: bool = False) -> dict | None:
    """Grade one finished call and store the result on the run; None when the
    call is not graded (test call, no conversation, no analysis model)."""
    from api.brand import db as brand_db
    from api.brand.analysis import _graph_index, resolve_analysis_model
    from api.brand.analysis_thresholds import load as load_thresholds
    from api.brand.llm import chat_json
    from api.brand.test_campaigns import agent_brief
    from api.brand.test_runs import _transcript, call_metrics
    from api.brand.test_technical import technical_report

    run_row = await db_client.get_workflow_run_by_id(run_id)
    if run_row is None or _skip(run_row):
        return None
    if not force and (run_row.annotations or {}).get(SCORE_KEY):
        return run_row.annotations[SCORE_KEY]
    workflow = await db_client.get_workflow_by_id(run_row.workflow_id)
    if workflow is None:
        return None
    org = workflow.organization_id
    runs = await brand_db.get_runs_by_ids([run_id], organization_id=org)
    if not runs:
        return None
    run = runs[0]
    transcript = _transcript(run)
    caller_spoke = any(line.lower().startswith(("caller", "user")) for line in transcript)
    if len(transcript) < 2 or not caller_spoke:
        return None

    graphs = await brand_db.get_definition_graphs(
        [run["definition_id"]], organization_id=org
    )
    index = _graph_index(graphs).get(run["definition_id"])
    metrics = call_metrics(run, index)
    channel = "text" if (run.get("mode") or "").lower() == "textchat" else "phone"
    thresholds = (await load_thresholds(org))["values"]
    technical = technical_report(
        [{"index": 1, "status": "done", "metrics": metrics, "scenario": {}}],
        thresholds,
        channel=channel,
    )
    graded = [p for p in technical.get("posts") or [] if p.get("score") is not None]
    weakest = min(graded, key=lambda p: p["score"]) if graded else None

    quality: dict = {}
    model = await resolve_analysis_model(org)
    if model:
        graph = (graphs.get(run["definition_id"]) or {}).get("workflow_json") or {}
        brief = agent_brief(graph, {})
        try:
            judge = await chat_json(
                model,
                QUALITY_PROMPT.replace("{language}", LANGUAGE),
                {
                    "agent": {
                        "name": run.get("workflow_name"),
                        "nodes": [
                            {
                                "name": n.get("name"),
                                "type": n.get("type"),
                                "prompt": (n.get("prompt") or "")[:800],
                            }
                            for n in brief.get("nodes") or []
                        ],
                        "transitions": brief.get("transitions"),
                    },
                    "transcript": transcript[:120],
                    "extracted_variables": metrics["extracted_variables"],
                    "ended": {
                        "status": metrics["end_status"],
                        "last_node": metrics["end_node"],
                    },
                },
                max_tokens=1200,
                timeout=120.0,
            )
            scores = {
                k: max(1, min(5, int(v)))
                for k, v in (judge.get("scores") or {}).items()
                if k in SCORE_KEYS and isinstance(v, (int, float))
            }
            quality = {
                "score": quality_score(scores),
                "scores": scores,
                "resolved": bool(judge.get("resolved")),
                "summary": str(judge.get("summary") or "")[:400],
                "issues": [str(i)[:300] for i in judge.get("issues") or []][:3],
                "model": model.get("model"),
            }
        except Exception as e:
            logger.warning(f"Call {run_id}: quality review failed: {e}")
            quality = {"error": str(e)[:200]}

    result = {
        "scored_at": datetime.now(UTC).isoformat(),
        "channel": channel,
        "quality": quality or None,
        "technical": {
            "score": technical.get("score"),
            "status": technical.get("status"),
            "weakest": weakest["label"] if weakest and weakest["score"] < 4 else None,
            "posts": [
                {
                    k: p.get(k)
                    for k in ("key", "label", "unit", "p50", "threshold", "score", "status")
                }
                for p in technical.get("posts") or []
            ],
        },
        "latency_p50_ms": metrics["latency"].get("p50_ms"),
        "perceived_p50_ms": metrics["latency"].get("perceived_p50_ms"),
    }
    await db_client.update_workflow_run(run_id, annotations={SCORE_KEY: result})
    logger.info(
        f"Call {run_id} scored: quality {(quality or {}).get('score')}, "
        f"technical {result['technical']['score']}"
    )
    return result


async def score_after_call(run_id: int) -> None:
    """Completion hook: never raises."""
    try:
        await score_run(run_id)
    except Exception as e:
        logger.warning(f"Call {run_id} not scored: {e}")
