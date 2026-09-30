"""Automatic fixes for the configuration analysis findings.

A fix goes through:

    proposing → proposed    the analysis model reads the finding, the agent
                            (nodes, transitions, settings) and the example
                            calls, and answers with constrained operations
    → applied               the operations are validated and saved as a draft
                            of the agent (version origin "fix"); the published
                            version keeps answering calls
    → testing → tested      the example calls are replayed as text against the
                            published version and the draft (simulation.py),
                            then compared (path metrics + model verdict)
    → published / discarded

``not_fixable`` findings (model latency, tool errors, pipeline errors…) only
get the analysis recommendation: fixing them is outside the agent.

Operations (all edits, never structure changes):
    {"op": "set_node_field", "node": <name or id>, "field": prompt|greeting|allow_interrupt|add_global_prompt, "value": …}
    {"op": "set_edge_field", "from": <node>, "to": <node>, "field": condition|label, "value": …}
    {"op": "set_setting", "key": <see SETTINGS>, "value": …}

Fixes are stored as organization configurations ``OXEE_FIX:<id>``.
"""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from api.brand import db as brand_db
from api.brand import versions
from api.db import db_client

PREFIX = "OXEE_FIX:"
ACTIVE = ("proposing", "proposed", "applied", "testing", "tested")
# One simulation at a time per API process: replays hammer the model endpoint.
_SIMULATIONS = asyncio.Lock()
MAX_FIXES = 200
MAX_CASES = 3

# --- What can be fixed --------------------------------------------------------

NOT_FIXABLE_RULES = {
    "reply_latency": "Reply latency comes from the models and the infrastructure, not from the agent's configuration.",
    "greeting_latency": "The greeting delay comes from the models and the infrastructure.",
    "dead_air_agent": "Silences before the agent answers come from model latency.",
    "tool_errors": "The tool itself fails: fix the webhook or the service it calls.",
    "tool_slow": "The tool itself is slow: speed up the service it calls.",
    "pipeline_errors": "Pipeline errors are technical failures, not configuration issues.",
}
REVIEW_RULES = {
    "pathway_never_taken": "A pathway never taken may be intended (rare cases).",
    "node_unreached": "A node never reached may be intended (rare cases).",
}
NOT_FIXABLE_CATEGORIES = {"latency", "tools", "reliability"}


def fixability(finding: dict) -> dict:
    rule = finding.get("rule") or ""
    if rule in NOT_FIXABLE_RULES:
        return {"fixable": False, "reason": NOT_FIXABLE_RULES[rule], "review": False}
    if rule.startswith("stage_"):
        return {
            "fixable": False,
            "reason": "A slow stage is a model / infrastructure matter.",
            "review": False,
        }
    if not rule and finding.get("category") in NOT_FIXABLE_CATEGORIES:
        return {
            "fixable": False,
            "reason": "This is not a configuration issue.",
            "review": False,
        }
    return {
        "fixable": True,
        "reason": REVIEW_RULES.get(rule),
        "review": rule in REVIEW_RULES,
    }


# --- Operations -----------------------------------------------------------------

NODE_FIELDS = {
    "prompt": str,
    "greeting": str,
    "allow_interrupt": bool,
    "add_global_prompt": bool,
}
EDGE_FIELDS = {"condition": str, "label": str}
SETTINGS = {
    "max_user_idle_timeout": (float, 3.0, 60.0),
    "smart_turn_stop_secs": (float, 0.5, 10.0),
    "speaking_plan.start.wait_seconds": (float, 0.0, 5.0),
    "speaking_plan.start.smart_endpointing": (str, None, None),
    "speaking_plan.start.on_punctuation_seconds": (float, 0.0, 3.0),
    "speaking_plan.start.on_no_punctuation_seconds": (float, 0.0, 3.0),
    "speaking_plan.start.on_number_seconds": (float, 0.0, 3.0),
    "speaking_plan.stop.num_words": (int, 0, 10),
    "speaking_plan.stop.voice_seconds": (float, 0.0, 0.5),
    "speaking_plan.stop.backoff_seconds": (float, 0.0, 10.0),
}


class FixError(ValueError):
    pass


def _find_node(nodes: list[dict], ref: Any) -> dict:
    ref = str(ref or "").strip()
    for n in nodes:
        if str(n.get("id")) == ref:
            return n
    matches = [
        n
        for n in nodes
        if str((n.get("data") or {}).get("name") or "").strip().lower() == ref.lower()
    ]
    if len(matches) == 1:
        return matches[0]
    raise FixError(
        f"unknown node “{ref}”" if not matches else f"several nodes are named “{ref}”"
    )


def _find_edge(graph: dict, op: dict) -> dict:
    edges = graph.get("edges") or []
    if op.get("edge"):
        for e in edges:
            if str(e.get("id")) == str(op["edge"]):
                return e
    nodes = graph.get("nodes") or []
    src = _find_node(nodes, op.get("from"))
    dst = _find_node(nodes, op.get("to"))
    matches = [
        e
        for e in edges
        if str(e.get("source")) == str(src["id"])
        and str(e.get("target")) == str(dst["id"])
    ]
    if op.get("label") and len(matches) > 1:
        matches = [
            e for e in matches if (e.get("data") or {}).get("label") == op["label"]
        ]
    if len(matches) != 1:
        raise FixError(
            f"no single transition from “{op.get('from')}” to “{op.get('to')}”"
        )
    return matches[0]


def _coerce(kind: type, value: Any, what: str) -> Any:
    if kind is bool:
        if isinstance(value, bool):
            return value
        raise FixError(f"{what} must be true or false")
    if kind is str:
        if not isinstance(value, str) or not value.strip():
            raise FixError(f"{what} must be a non-empty text")
        return value
    try:
        return kind(value)
    except (TypeError, ValueError) as e:
        raise FixError(f"{what} must be a number") from e


def _speaking_plan_config(plan: dict) -> dict:
    """Plan + the upstream turn keys kept in line (as the settings page does)."""
    return {
        "speaking_plan": plan,
        "turn_stop_strategy": (
            "turn_analyzer"
            if plan["start"]["smart_endpointing"] == "smart_turn"
            else "transcription"
        ),
        "turn_start_strategy": (
            "min_words" if plan["stop"]["num_words"] > 0 else "default"
        ),
        "turn_start_min_words": max(1, plan["stop"]["num_words"] or 3),
    }


def apply_operations(
    workflow_json: dict, configurations: dict, operations: list[dict]
) -> tuple[dict, dict, list[dict]]:
    """Apply validated operations to copies; returns (json, configurations, applied)."""
    from api.brand.speaking_plan import SpeakingPlan
    from api.brand.versions import _speaking_plan_from_turn_settings

    graph = copy.deepcopy(workflow_json or {})
    cfg = copy.deepcopy(configurations or {})
    applied: list[dict] = []
    if not operations:
        raise FixError("the proposal has no operation")
    for i, op in enumerate(operations):
        kind = op.get("op")
        where = f"operation {i + 1}"
        if kind == "set_node_field":
            node = _find_node(graph.get("nodes") or [], op.get("node"))
            field = op.get("field")
            if field not in NODE_FIELDS:
                raise FixError(f"{where}: node field “{field}” cannot be changed")
            data = node.setdefault("data", {})
            before = data.get(field)
            data[field] = _coerce(
                NODE_FIELDS[field], op.get("value"), f"{where}: {field}"
            )
            applied.append(
                {
                    "target": f"node “{data.get('name')}”",
                    "field": field,
                    "before": before,
                    "after": data[field],
                }
            )
        elif kind == "set_edge_field":
            edge = _find_edge(graph, op)
            field = op.get("field")
            if field not in EDGE_FIELDS:
                raise FixError(f"{where}: transition field “{field}” cannot be changed")
            data = edge.setdefault("data", {})
            before = data.get(field)
            data[field] = _coerce(
                EDGE_FIELDS[field], op.get("value"), f"{where}: {field}"
            )
            applied.append(
                {
                    "target": f"transition “{op.get('from')} → {op.get('to')}”",
                    "field": field,
                    "before": before,
                    "after": data[field],
                }
            )
        elif kind == "set_setting":
            key = op.get("key")
            if key not in SETTINGS:
                raise FixError(f"{where}: setting “{key}” cannot be changed")
            typ, lo, hi = SETTINGS[key]
            value = _coerce(typ, op.get("value"), f"{where}: {key}")
            if lo is not None and not (lo <= value <= hi):
                raise FixError(f"{where}: {key} must be between {lo} and {hi}")
            if key.startswith("speaking_plan."):
                plan = copy.deepcopy(
                    cfg.get("speaking_plan") or _speaking_plan_from_turn_settings(cfg)
                )
                _, part, name = key.split(".")
                before = plan[part].get(name)
                plan[part][name] = value
                try:
                    plan = SpeakingPlan.model_validate(plan).model_dump()
                except Exception as e:
                    raise FixError(f"{where}: {e}") from e
                cfg.update(_speaking_plan_config(plan))
            else:
                before = cfg.get(key)
                cfg[key] = value
            applied.append(
                {"target": "settings", "field": key, "before": before, "after": value}
            )
        else:
            raise FixError(f"{where}: unknown operation “{kind}”")
    return graph, cfg, applied


def validate_graph(workflow_json: dict) -> None:
    from api.services.workflow.dto import ReactFlowDTO
    from api.services.workflow.workflow_graph import WorkflowGraph

    try:
        WorkflowGraph(
            ReactFlowDTO.model_validate(workflow_json),
            skip_instance_constraints_for={"trigger"},
        )
    except Exception as e:
        raise FixError(f"the fixed agent is not valid: {e}") from e


# --- Storage --------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def save(organization_id: int, fix: dict) -> dict:
    fix["updated_at"] = _now()
    await db_client.upsert_configuration(organization_id, PREFIX + fix["id"], fix)
    return fix


async def get(organization_id: int, fix_id: str) -> dict | None:
    row = await db_client.get_configuration(organization_id, PREFIX + fix_id)
    return dict(row.value) if row and row.value else None


async def list_fixes(
    organization_id: int,
    *,
    report_id: str | None = None,
    workflow_id: int | None = None,
) -> list[dict]:
    items = await brand_db.list_configurations_by_prefix(
        organization_id, PREFIX, limit=MAX_FIXES
    )
    if report_id:
        items = [f for f in items if f.get("report_id") == report_id]
    if workflow_id:
        items = [f for f in items if f.get("workflow_id") == workflow_id]
    return items


# --- Context for the model -------------------------------------------------------


def agent_outline(workflow_json: dict, configurations: dict) -> dict:
    from api.brand.versions import _speaking_plan_from_turn_settings

    nodes = workflow_json.get("nodes") or []
    names = {str(n.get("id")): (n.get("data") or {}).get("name") for n in nodes}
    return {
        "nodes": [
            {
                "name": (n.get("data") or {}).get("name"),
                "type": n.get("type"),
                **{
                    k: (n.get("data") or {}).get(k)
                    for k in NODE_FIELDS
                    if (n.get("data") or {}).get(k) is not None
                },
            }
            for n in nodes
        ],
        "transitions": [
            {
                "from": names.get(str(e.get("source"))),
                "to": names.get(str(e.get("target"))),
                "label": (e.get("data") or {}).get("label"),
                "condition": (e.get("data") or {}).get("condition"),
            }
            for e in workflow_json.get("edges") or []
        ],
        "settings": {
            "speaking_plan": configurations.get("speaking_plan")
            or _speaking_plan_from_turn_settings(configurations),
            "max_user_idle_timeout": configurations.get("max_user_idle_timeout", 10.0),
            "smart_turn_stop_secs": configurations.get("smart_turn_stop_secs", 2.0),
        },
    }


def call_excerpt(run: dict) -> dict:
    events = (run.get("logs") or {}).get("realtime_feedback_events") or []
    lines = []
    for e in events:
        t, p = e.get("type"), e.get("payload") or {}
        if (
            t == "rtf-user-transcription"
            and p.get("final") is not False
            and p.get("text")
        ):
            lines.append(f"CALLER: {p['text']}")
        elif t == "rtf-bot-text" and p.get("text"):
            lines.append(
                f"AGENT [{e.get('node_name') or '?'}]{' (interrupted)' if p.get('interrupted') else ''}: {p['text']}"
            )
        elif t == "rtf-node-transition":
            lines.append(f"--> node “{p.get('node_name')}”")
        elif t == "rtf-function-call-end":
            lines.append(
                f"TOOL {p.get('function_name')} → {json.dumps(p.get('result'), ensure_ascii=False, default=str)[:200]}"
            )
    return {
        "call": run["id"],
        "status": (run.get("gathered_context") or {}).get("call_status"),
        "transcript": lines[:80],
    }


# --- Proposal ---------------------------------------------------------------------

FIX_PROMPT = """You fix the configuration of a phone voice agent built as a graph:
nodes (each with a prompt the LLM follows while in that node, an optional
greeting) linked by transitions (the LLM moves to another node by calling the
transition whose condition matches), plus settings (speaking plan = turn-taking,
idle timeout).

You receive one finding from an analysis of recorded calls, the agent, and
excerpts of example calls. Propose the smallest configuration change that fixes
the finding without breaking what works.

Allowed operations (nothing else, no new nodes or transitions):
- {"op": "set_node_field", "node": "<node name>", "field": "prompt"|"greeting"|"allow_interrupt"|"add_global_prompt", "value": <full new value>}
- {"op": "set_edge_field", "from": "<node name>", "to": "<node name>", "field": "condition", "value": "<full new condition>"}
- {"op": "set_setting", "key": "<key>", "value": <number or text>} with key in:
  max_user_idle_timeout (3-60 s): seconds of caller silence before the agent
    asks whether the caller is still there; after a SECOND such silence the
    call is HUNG UP. Below 8 s callers who look something up get cut off.
  smart_turn_stop_secs (0.5-10 s): with Smart Turn endpointing, silence after
    which an unfinished sentence still ends the caller's turn.
  speaking_plan.start.wait_seconds (0-5): minimum delay before the agent answers.
  speaking_plan.start.smart_endpointing ("off"|"smart_turn"): who decides the
    caller has finished (transcript rules or the Smart Turn model).
  speaking_plan.start.on_punctuation_seconds / on_no_punctuation_seconds /
    on_number_seconds (0-3): silence needed after a transcript ending with
    punctuation / without / with a number before the agent answers.
  speaking_plan.stop.num_words (0-10): words the caller must say to interrupt
    the agent (0 = any voice).
  speaking_plan.stop.voice_seconds (0-0.5): speech needed to count as voice.
  speaking_plan.stop.backoff_seconds (0-10): pause after an interruption
    before the agent speaks again.

Rules:
- Example calls marked made_on_the_published_version=false were made on an
  earlier version: the agent you receive may already address them; do not
  undo recent changes because of them.
- "value" of a prompt or condition is the COMPLETE new text: keep everything
  that still applies, change only what fixes the finding, keep the original
  language and tone of the agent.
- Routing problems (loops, back-and-forth, wrong or missing transitions): make
  the conditions of the transitions leaving the node precise and mutually
  exclusive, and tell the node's prompt when to move on and when not to.
- Caller interrupting / talking over the agent: shorter replies in the prompt,
  and/or the stop speaking plan. Callers silent or hanging up: prompt (ask a
  clear question, re-engage) and/or the idle timeout.
- A prompt cannot measure time or silences: never write timing behaviour
  ("if the caller does not answer within 5 seconds…") in a prompt; silences
  are handled by the settings above.
- Only change a setting when the calls show it is the cause; keep its value
  within what callers need (see the notes above).
- If the finding cannot be fixed by these operations, or is probably intended,
  answer fixable=false with the reason.

Write "summary", "rationale", "expected_effect", "risks" and "test_focus" in {language}.
Answer only with JSON:
{"fixable": bool, "reason": str, "summary": str, "rationale": str,
 "operations": [...], "expected_effect": str, "risks": [str], "test_focus": str}"""


def _finding_view(finding: dict) -> dict:
    return {
        k: finding.get(k)
        for k in (
            "rule",
            "severity",
            "category",
            "title",
            "detail",
            "agent",
            "node",
            "metrics",
            "recommendation",
        )
    }


async def _published(workflow_id: int, organization_id: int):
    workflow = await db_client.get_workflow(
        workflow_id, organization_id=organization_id
    )
    if workflow is None:
        raise FixError("agent not found")
    definition = (
        await brand_db.get_workflow_version(
            workflow_id, workflow.released_definition_id
        )
        if workflow.released_definition_id
        else None
    )
    return workflow, definition


async def resolve_workflow(
    organization_id: int, report: dict, finding: dict
) -> int | None:
    links = report.get("call_links") or {}
    for call in finding.get("calls") or []:
        if str(call) in links:
            return int(links[str(call)])
    if report.get("workflow_id"):
        return int(report["workflow_id"])
    if finding.get("agent"):
        return await brand_db.find_workflow_by_name(organization_id, finding["agent"])
    return None


async def create(
    organization_id: int, user: Any, report: dict, finding: dict, *, language: str
) -> dict:
    fx = fixability(finding)
    workflow_id = await resolve_workflow(organization_id, report, finding)
    fix = {
        "id": uuid.uuid4().hex[:12],
        "created_at": _now(),
        "created_by": {
            "id": getattr(user, "id", None),
            "email": getattr(user, "email", None),
        },
        "via": versions.current_channel().get("channel"),
        "report_id": report.get("id"),
        "finding": {
            **_finding_view(finding),
            "id": finding.get("id"),
            "calls": finding.get("calls") or [],
        },
        "workflow_id": workflow_id,
        "language": language,
        "review": fx["review"],
        "review_reason": fx["reason"] if fx["review"] else None,
        "status": "proposing" if fx["fixable"] and workflow_id else "not_fixable",
        "reason": (
            None
            if fx["fixable"] and workflow_id
            else (fx["reason"] or "The agent of this finding could not be found.")
        ),
    }
    return await save(organization_id, fix)


async def propose(organization_id: int, fix_id: str) -> None:
    """Background: ask the analysis model for operations and check them."""
    from api.brand.analysis import resolve_analysis_model
    from api.brand.llm import chat_json

    fix = await get(organization_id, fix_id)
    if fix is None:
        return
    try:
        workflow, published = await _published(fix["workflow_id"], organization_id)
        if published is None:
            raise FixError("the agent has no published version")
        fix["workflow_name"] = workflow.name
        fix["base_definition_id"] = published.id
        fix["base_version_number"] = published.version_number
        model = await resolve_analysis_model(organization_id)
        if not model:
            raise FixError("no analysis model configured (Models › Analysis)")
        all_runs = await brand_db.get_runs_by_ids(
            fix["finding"]["calls"], organization_id=organization_id
        )
        prior = await _prior_published_fix(organization_id, fix)
        if (
            prior
            and all_runs
            and all(r.get("definition_id") != published.id for r in all_runs)
        ):
            # The calls predate the fix already in production: proposing again
            # would undo it. Its follow-up tells whether it works.
            fix.update(
                status="not_fixable",
                reason=f"Already fixed in v{prior.get('draft_version_number')} "
                f"(published {str(prior.get('updated_at', ''))[:10]}): these calls were "
                "made on an earlier version. Check the follow-up of that fix once "
                "the new version has answered calls.",
                prior_fix_id=prior["id"],
            )
            await save(organization_id, fix)
            return
        runs = all_runs[:MAX_CASES]
        payload = {
            "finding": fix["finding"],
            "agent": agent_outline(
                published.workflow_json or {}, published.workflow_configurations or {}
            ),
            "published_version": published.version_number,
            "example_calls": [
                {
                    **call_excerpt(r),
                    "made_on_the_published_version": r.get("definition_id")
                    == published.id,
                }
                for r in runs
            ],
        }
        result = await chat_json(
            model,
            FIX_PROMPT.replace("{language}", fix["language"]),
            payload,
            max_tokens=6000,
            timeout=180.0,
        )
        fix["model"] = model["model"]
        if not result.get("fixable", True):
            fix.update(
                status="not_fixable",
                reason=str(
                    result.get("reason") or "The model found no configuration fix."
                ),
            )
        else:
            operations = [
                o for o in result.get("operations") or [] if isinstance(o, dict)
            ]
            # Check now: an invalid proposal must never reach a draft.
            new_json, new_cfg, applied = apply_operations(
                published.workflow_json or {},
                published.workflow_configurations or {},
                operations,
            )
            validate_graph(new_json)
            fix.update(
                status="proposed",
                proposal={
                    "summary": str(result.get("summary") or ""),
                    "rationale": str(result.get("rationale") or ""),
                    "expected_effect": str(result.get("expected_effect") or ""),
                    "risks": [str(r) for r in result.get("risks") or []][:5],
                    "test_focus": str(result.get("test_focus") or ""),
                    "operations": operations,
                    "applied_preview": applied,
                },
            )
    except Exception as e:
        logger.warning(f"Fix {fix_id}: proposal failed: {e}")
        fix.update(status="failed", error=str(e))
    await save(organization_id, fix)


async def _prior_published_fix(organization_id: int, fix: dict) -> dict | None:
    """A published fix of the same rule / agent / node from another report."""
    rule = fix["finding"].get("rule")
    if not rule:
        return None
    for other in await list_fixes(organization_id, workflow_id=fix.get("workflow_id")):
        f = other.get("finding") or {}
        if (
            other["id"] != fix["id"]
            and other.get("status") == "published"
            and f.get("rule") == rule
            and f.get("node") == fix["finding"].get("node")
        ):
            return other
    return None


async def preview_diff(organization_id: int, fix: dict) -> dict | None:
    """Diff published → published + operations (before anything is saved)."""
    from api.brand.version_diff import diff_versions
    from api.brand.versions import _snapshot

    if not fix.get("proposal") or not fix.get("base_definition_id"):
        return None
    base = await brand_db.get_workflow_version(
        fix["workflow_id"], fix["base_definition_id"]
    )
    if base is None:
        return None
    new_json, new_cfg, _ = apply_operations(
        base.workflow_json or {},
        base.workflow_configurations or {},
        fix["proposal"]["operations"],
    )

    class _V:
        workflow_json = new_json
        workflow_configurations = new_cfg
        template_context_variables = base.template_context_variables

    return diff_versions(_snapshot(base), _snapshot(_V))


# --- Apply ------------------------------------------------------------------------


async def apply(
    organization_id: int, fix_id: str, user: Any, *, replace_draft: bool = False
) -> dict:
    fix = await get(organization_id, fix_id)
    if fix is None:
        raise LookupError("fix not found")
    if fix["status"] not in ("proposed", "failed") or not fix.get("proposal"):
        raise FixError(f"a fix in status “{fix['status']}” cannot be applied")
    workflow_id = fix["workflow_id"]
    draft = await db_client.get_draft_version(workflow_id)
    base = None
    if draft is not None:
        meta = await versions.get_meta(organization_id, workflow_id, draft.id)
        if meta.get("origin") == "fix" and not replace_draft:
            base = draft  # combine with the other fixes of this draft
        elif replace_draft:
            await versions.discard_draft(workflow_id, organization_id=organization_id)
        else:
            raise versions.DraftExists(draft)
    if base is None:
        _, base = await _published(workflow_id, organization_id)
        if base is None:
            raise FixError("the agent has no published version")
    new_json, new_cfg, applied = apply_operations(
        base.workflow_json or {},
        base.workflow_configurations or {},
        fix["proposal"]["operations"],
    )
    validate_graph(new_json)
    saved = await db_client.save_workflow_draft(
        workflow_id, workflow_definition=new_json, workflow_configurations=new_cfg
    )
    await versions.record_edit(
        saved,
        user,
        organization_id=organization_id,
        origin="fix",
        note=f"Automatic fix: {fix['finding']['title']}",
    )
    meta = await versions.get_meta(organization_id, workflow_id, saved.id)
    meta["fixes"] = sorted({*(meta.get("fixes") or []), fix_id})
    await versions._save_meta(organization_id, workflow_id, saved.id, meta)
    fix.update(
        status="applied",
        draft_definition_id=saved.id,
        draft_version_number=saved.version_number,
        combined_with=[f for f in meta["fixes"] if f != fix_id],
        applied=applied,
        applied_at=_now(),
        simulation=None,
        error=None,
    )
    return await save(organization_id, fix)


async def discard(organization_id: int, fix_id: str) -> dict:
    """Drop the fix; its draft goes too when it holds no other fix."""
    fix = await get(organization_id, fix_id)
    if fix is None:
        raise LookupError("fix not found")
    if fix.get("draft_definition_id") and fix["status"] in (
        "applied",
        "testing",
        "tested",
    ):
        draft = await db_client.get_draft_version(fix["workflow_id"])
        if draft is not None and draft.id == fix["draft_definition_id"]:
            meta = await versions.get_meta(
                organization_id, fix["workflow_id"], draft.id
            )
            others = [f for f in meta.get("fixes") or [] if f != fix_id]
            if others:
                raise FixError(
                    "the draft also holds other fixes: discard it from the versions page"
                )
            await versions.discard_draft(
                fix["workflow_id"], organization_id=organization_id
            )
    fix["status"] = "discarded"
    return await save(organization_id, fix)


# --- Simulation -------------------------------------------------------------------

JUDGE_PROMPT = """You check whether a configuration fix of a phone voice agent
works. The same caller turns (taken from real calls) were replayed as text
against the version in production ("baseline") and the fixed draft
("candidate"). The replay is open loop: the caller's words do not adapt to the
agent, so judge the agent's behaviour, routing and replies, not the caller's.

For each case compare baseline and candidate with the finding, the expected
effect and the test focus: "improved", "unchanged" or "regressed", with one
short sentence.
- "regressed" only when the candidate does clearly worse than the baseline on
  the same caller turn. A problem present in both versions is "unchanged".
- When a scripted caller line does not answer the agent's question (the real
  caller was answering something else), both versions are stuck the same way:
  do not count it against either.
- Small wording differences are normal (the model is not deterministic).
Then give an overall verdict:
- "pass": the finding is fixed in the cases where it showed, nothing regressed;
- "mixed": partly fixed, or fixed with side effects worth a look;
- "fail": not fixed, or something regressed;
- "inconclusive": the replay cannot show the effect. Text replays have no
  timing: silences, idle timeout, speaking plan and interruptions are not
  exercised, so a fix made only of such settings is inconclusive unless its
  prompt changes show.

Write in {language}. Answer only with JSON:
{"verdict": "pass"|"mixed"|"fail"|"inconclusive", "summary": str,
 "cases": [{"case": <number>, "verdict": "improved"|"unchanged"|"regressed", "notes": str}]}"""


VERDICTS = ("pass", "mixed", "fail", "inconclusive")


def overall_verdict(model_verdict: str | None, cases: list[dict]) -> str | None:
    """The model's overall verdict, or one derived from the case verdicts."""
    if any((c.get("candidate") or {}).get("error") for c in cases):
        return "fail"
    if model_verdict in VERDICTS:
        return model_verdict
    seen = {c.get("verdict") for c in cases if c.get("verdict")}
    if not seen:
        return None
    if "regressed" in seen:
        return "fail"
    if seen == {"improved"}:
        return "pass"
    if "improved" in seen:
        return "mixed"
    return "inconclusive"


def _trim(transcript: list[dict], limit: int = 40) -> list[str]:
    out = []
    for m in transcript[:limit]:
        who = {
            "caller": "CALLER",
            "agent": f"AGENT [{m.get('node') or '?'}]",
            "system": "--",
        }[m["role"]]
        out.append(f"{who}: {m['text'][:400]}")
    return out


async def simulate(
    organization_id: int, fix_id: str, user_id: int, *, max_cases: int = MAX_CASES
) -> None:
    """Background: replay the example calls on the published version and the draft."""
    if _SIMULATIONS.locked():
        fix = await get(organization_id, fix_id)
        if fix is not None:
            fix["simulation"] = {"status": "queued", "cases": []}
            await save(organization_id, fix)
    async with _SIMULATIONS:
        await _simulate(organization_id, fix_id, user_id, max_cases=max_cases)


async def _simulate(
    organization_id: int, fix_id: str, user_id: int, *, max_cases: int
) -> None:
    from api.brand import simulation as sim
    from api.brand.analysis import resolve_analysis_model
    from api.brand.llm import chat_json

    fix = await get(organization_id, fix_id)
    if fix is None:
        return
    workflow_id = fix["workflow_id"]
    try:
        _, published = await _published(workflow_id, organization_id)
        draft = await db_client.get_draft_version(workflow_id)
        if draft is None or draft.id != fix.get("draft_definition_id"):
            raise FixError(
                "the draft of this fix no longer exists (published or discarded)"
            )
        ids = [c for c in fix["finding"].get("calls") or []]
        runs = [
            r
            for r in await brand_db.get_runs_by_ids(
                ids, organization_id=organization_id
            )
            if r["workflow_id"] == workflow_id
        ]
        if len(runs) < max_cases:
            runs += [
                r
                for r in await brand_db.recent_calls(
                    workflow_id, organization_id=organization_id, limit=10
                )
                if r["id"] not in {x["id"] for x in runs}
            ]
        cases_src = [
            r
            for r in runs
            if len(
                sim.caller_script(
                    (r.get("logs") or {}).get("realtime_feedback_events") or []
                )
            )
            >= 1
        ][:max_cases]
        if not cases_src:
            raise FixError("no recorded call with caller turns to replay")
        fix["simulation"] = {
            "status": "running",
            "started_at": _now(),
            "cases": [],
            "total": len(cases_src),
        }
        fix["status"] = "testing"
        await save(organization_id, fix)

        cases = []
        for i, run in enumerate(cases_src, 1):
            events = (run.get("logs") or {}).get("realtime_feedback_events") or []
            script = sim.caller_script(events)
            tools = sim.recorded_tool_results(events)
            common = dict(
                workflow_id=workflow_id,
                user_id=user_id,
                organization_id=organization_id,
                script=script,
                tool_results=tools,
            )
            baseline = (
                await sim.replay(
                    definition_id=published.id,
                    use_draft=False,
                    label=f"{fix_id}-c{i}-published",
                    **common,
                )
                if published
                else None
            )
            candidate = await sim.replay(
                definition_id=draft.id,
                use_draft=True,
                label=f"{fix_id}-c{i}-draft",
                **common,
            )
            for side in (baseline, candidate):
                if side:
                    side["metrics"] = sim.path_metrics(side["path"], side["transcript"])
            cases.append(
                {
                    "case": i,
                    "source_call": run["id"],
                    "caller_turns": len(script),
                    "original_path": sim.recorded_path(events),
                    "baseline": baseline,
                    "candidate": candidate,
                }
            )
            fix["simulation"]["cases"] = cases
            await save(organization_id, fix)

        verdict = {"verdict": None, "summary": "", "cases": []}
        model = await resolve_analysis_model(organization_id)
        if model:
            payload = {
                "finding": fix["finding"],
                "fix": {
                    k: fix["proposal"].get(k)
                    for k in ("summary", "expected_effect", "test_focus")
                },
                "cases": [
                    {
                        "case": c["case"],
                        "original_call_path": c["original_path"],
                        "baseline": (
                            {
                                "path": c["baseline"]["path"],
                                "metrics": c["baseline"]["metrics"],
                                "error": c["baseline"]["error"],
                                "transcript": _trim(c["baseline"]["transcript"]),
                            }
                            if c["baseline"]
                            else None
                        ),
                        "candidate": {
                            "path": c["candidate"]["path"],
                            "metrics": c["candidate"]["metrics"],
                            "error": c["candidate"]["error"],
                            "transcript": _trim(c["candidate"]["transcript"]),
                        },
                    }
                    for c in cases
                ],
            }
            try:
                verdict = await chat_json(
                    model,
                    JUDGE_PROMPT.replace(
                        "{language}", fix.get("language") or "English"
                    ),
                    payload,
                    max_tokens=3000,
                    timeout=180.0,
                )
            except Exception as e:  # keep the replays; only the verdict is missing
                logger.warning(f"Fix {fix_id}: judge failed: {e}")
                verdict = {"verdict": None, "summary": "", "cases": [], "error": str(e)}
        by_case = {
            int(v.get("case", 0)): v
            for v in verdict.get("cases") or []
            if isinstance(v, dict)
        }
        for c in cases:
            v = by_case.get(c["case"]) or {}
            c["verdict"] = (
                v.get("verdict")
                if v.get("verdict") in ("improved", "unchanged", "regressed")
                else None
            )
            c["notes"] = str(v.get("notes") or "")
        fix["simulation"].update(
            status="done",
            finished_at=_now(),
            cases=cases,
            verdict=overall_verdict(verdict.get("verdict"), cases),
            summary=str(verdict.get("summary") or ""),
            model=model["model"] if model else None,
            judge_error=verdict.get("error"),
        )
        fix["status"] = "tested"
    except Exception as e:
        logger.warning(f"Fix {fix_id}: simulation failed: {e}")
        fix["simulation"] = {
            **(fix.get("simulation") or {}),
            "status": "failed",
            "error": str(e),
            "finished_at": _now(),
        }
        fix["status"] = "applied"
    await save(organization_id, fix)


# --- After publication ----------------------------------------------------------

MIN_CALLS_AFTER = 3
FOLLOW_UP_WINDOW = 50


async def follow_up(organization_id: int, fix_id: str) -> dict:
    """Is the finding gone from the real calls made on the fixed version?

    The same rules as the analysis run on the calls of the published fix
    version and on the calls of the version it replaced (same thresholds).
    Findings from the model (no rule) are checked by a new analysis instead.
    """
    from api.brand.analysis import SEVERITY_ORDER, run_rules
    from api.brand.analysis_thresholds import load as load_thresholds

    fix = await get(organization_id, fix_id)
    if fix is None:
        raise LookupError("fix not found")
    if fix.get("status") not in ("published", "rolled_back"):
        raise FixError("follow-up starts once the fix is published")
    finding = fix["finding"]
    rule = finding.get("rule")
    result: dict[str, Any] = {"checked_at": _now(), "min_calls": MIN_CALLS_AFTER}
    after_runs = await brand_db.recent_calls(
        fix["workflow_id"],
        organization_id=organization_id,
        limit=FOLLOW_UP_WINDOW,
        definition_id=fix["draft_definition_id"],
    )
    result["calls_after"] = len(after_runs)
    if not rule:
        result.update(
            status="manual", note="Found by the model: run a new analysis to check it."
        )
    elif len(after_runs) < MIN_CALLS_AFTER:
        result.update(status="waiting")
    else:
        before_runs = await brand_db.recent_calls(
            fix["workflow_id"],
            organization_id=organization_id,
            limit=FOLLOW_UP_WINDOW,
            definition_id=fix.get("base_definition_id"),
        )
        graphs = await brand_db.get_definition_graphs(
            [r["definition_id"] for r in after_runs + before_runs],
            organization_id=organization_id,
        )
        th = (await load_thresholds(organization_id))["values"]

        def matching(runs: list[dict]) -> list[dict]:
            if not runs:
                return []
            found, _, _ = run_rules(runs, graphs, th)
            return [
                f
                for f in found
                if f.get("rule") == rule
                and (not finding.get("node") or f.get("node") == finding.get("node"))
            ]

        before, after = matching(before_runs), matching(after_runs)
        brief = lambda f: {
            k: f.get(k) for k in ("severity", "title", "calls", "metrics")
        }  # noqa: E731
        result.update(
            calls_before=len(before_runs),
            before=brief(before[0]) if before else None,
            after=brief(after[0]) if after else None,
        )
        if not after:
            result["status"] = "fixed"
        elif (
            not before
            or SEVERITY_ORDER[after[0]["severity"]]
            < SEVERITY_ORDER[before[0]["severity"]]
        ):
            result["status"] = "worse"
        else:
            result["status"] = "still_present"
    fix["follow_up"] = result
    await save(organization_id, fix)
    return result


async def rollback(
    organization_id: int, fix_id: str, user: Any, *, replace_draft: bool = False
) -> dict:
    """Put back the version the fix replaced, as a new published version."""
    fix = await get(organization_id, fix_id)
    if fix is None:
        raise LookupError("fix not found")
    if fix.get("status") != "published":
        raise FixError("only a published fix can be rolled back")
    workflow_id = fix["workflow_id"]
    workflow = await db_client.get_workflow(
        workflow_id, organization_id=organization_id
    )
    if workflow is None:
        raise LookupError("agent not found")
    if workflow.released_definition_id != fix.get("draft_definition_id"):
        current = await brand_db.get_workflow_version(
            workflow_id, workflow.released_definition_id
        )
        raise FixError(
            f"the agent was published again since the fix (now v{current.version_number if current else '?'}): "
            "restore the version you want from the versions page"
        )
    note = f"Rollback of the automatic fix: {fix['finding']['title']}"
    restored = await versions.restore(
        workflow_id,
        fix["base_definition_id"],
        user,
        organization_id=organization_id,
        replace_draft=replace_draft,
        note=note,
    )
    published = await db_client.publish_workflow_draft(workflow_id)
    await versions.record_published(published, user, organization_id=organization_id)
    # Every fix of that version goes back with it.
    meta = await versions.get_meta(
        organization_id, workflow_id, fix["draft_definition_id"]
    )
    for other_id in meta.get("fixes") or [fix_id]:
        other = await get(organization_id, other_id)
        if other and other.get("status") == "published":
            other.update(
                status="rolled_back",
                rolled_back_to=restored.version_number,
                rolled_back_at=_now(),
                rolled_back_by={
                    "id": getattr(user, "id", None),
                    "email": getattr(user, "email", None),
                },
            )
            await save(organization_id, other)
    return await get(organization_id, fix_id)
