"""Detection thresholds for the configuration analysis.

Every rule threshold is described here (meaning, unit, built-in default,
allowed range). Organizations store their own values under
``OXEE_ANALYSIS_THRESHOLDS``; by default they are proposed by the analysis
model from the agents' use case and what the calls show, and can be edited on
the Analysis page. Values are always clamped to the allowed range.
"""

import json
from datetime import UTC, datetime
from statistics import median
from typing import Any

import httpx

THRESHOLDS_KEY = "OXEE_ANALYSIS_THRESHOLDS"

# key: (group, label, description, unit, default, min, max, step)
SPEC: list[dict[str, Any]] = [
    {
        "key": "reply_p50_warn_ms",
        "group": "Latency",
        "label": "Slow first audio (warning)",
        "unit": "ms",
        "description": "Median time to first audio above which replies are flagged: from the end of the caller's turn to the agent's first audio, without the end-of-turn wait (a setting of the agent, judged on its own).",
        "default": 1800,
        "min": 500,
        "max": 10000,
        "step": 100,
    },
    {
        "key": "reply_p50_crit_ms",
        "group": "Latency",
        "label": "Slow first audio (critical)",
        "unit": "ms",
        "description": "Median time to first audio (end-of-turn wait not counted) above which the finding becomes critical.",
        "default": 2800,
        "min": 800,
        "max": 15000,
        "step": 100,
    },
    {
        "key": "llm_stage_warn_ms",
        "group": "Latency",
        "label": "LLM stage",
        "unit": "ms",
        "description": "Average LLM time per reply (first token + streaming to the first sentence).",
        "default": 1500,
        "min": 200,
        "max": 10000,
        "step": 50,
    },
    {
        "key": "transcriber_stage_warn_ms",
        "group": "Latency",
        "label": "Transcriber stage",
        "unit": "ms",
        "description": "Average speech-to-text time per reply.",
        "default": 800,
        "min": 100,
        "max": 5000,
        "step": 50,
    },
    {
        "key": "voice_stage_warn_ms",
        "group": "Latency",
        "label": "Voice stage",
        "unit": "ms",
        "description": "Average text-to-speech time to first audio.",
        "default": 700,
        "min": 100,
        "max": 5000,
        "step": 50,
    },
    {
        "key": "voice_speed_warn",
        "group": "Latency",
        "label": "Voice generation speed (warning)",
        "unit": "x real time",
        "description": "Seconds of speech generated per second of synthesis below which the voice is flagged: close to 1, the voice model barely keeps up and callers may hear gaps inside sentences.",
        "default": 1.5,
        "min": 1.0,
        "max": 5.0,
        "step": 0.1,
    },
    {
        "key": "voice_speed_crit",
        "group": "Latency",
        "label": "Voice generation speed (critical)",
        "unit": "x real time",
        "description": "Generation speed below which the voice is critical (gaps are likely).",
        "default": 1.1,
        "min": 0.5,
        "max": 4.0,
        "step": 0.1,
    },
    {
        "key": "endpointing_stage_warn_ms",
        "group": "Latency",
        "label": "End-of-turn detection",
        "unit": "ms",
        "description": "Average wait before the agent decides the caller has finished (VAD silence + speaking plan). A setting rather than processing: not counted in the time to first audio.",
        "default": 900,
        "min": 100,
        "max": 5000,
        "step": 50,
    },
    {
        "key": "greeting_warn_ms",
        "group": "Latency",
        "label": "Greeting delay",
        "unit": "ms",
        "description": "Average time before the agent speaks after the call connects.",
        "default": 1500,
        "min": 200,
        "max": 10000,
        "step": 100,
    },
    {
        "key": "dead_air_secs",
        "group": "Silences",
        "label": "Dead air",
        "unit": "s",
        "description": "Silence between two messages long enough to be flagged.",
        "default": 4.0,
        "min": 1.0,
        "max": 30.0,
        "step": 0.5,
    },
    {
        "key": "node_turns_warn",
        "group": "Conversation flow",
        "label": "Stalled node",
        "unit": "caller turns",
        "description": "Caller turns within one node visit that indicate the conversation is stuck.",
        "default": 8,
        "min": 2,
        "max": 50,
        "step": 1,
    },
    {
        "key": "node_secs_warn",
        "group": "Conversation flow",
        "label": "Long time in a node",
        "unit": "s",
        "description": "Average time per node visit above which the node is flagged.",
        "default": 90.0,
        "min": 10.0,
        "max": 1800.0,
        "step": 5,
    },
    {
        "key": "interruption_rate_warn",
        "group": "Conversation flow",
        "label": "Interruption rate",
        "unit": "%",
        "description": "Share of the agent's messages cut off by the caller in a node.",
        "default": 0.25,
        "min": 0.05,
        "max": 0.9,
        "step": 0.01,
    },
    {
        "key": "ping_pong_secs",
        "group": "Routing",
        "label": "Back-and-forth window",
        "unit": "s",
        "description": "A move A → B then back to A within this time is flagged as back-and-forth routing.",
        "default": 45.0,
        "min": 5.0,
        "max": 600.0,
        "step": 5,
    },
    {
        "key": "hangup_after_transition_secs",
        "group": "Routing",
        "label": "Hang-up after a transition",
        "unit": "s",
        "description": "A hang-up this soon after entering a (non-end) node suggests wrong routing.",
        "default": 12.0,
        "min": 2.0,
        "max": 120.0,
        "step": 1,
    },
    {
        "key": "tool_error_rate_warn",
        "group": "Tools",
        "label": "Tool error rate",
        "unit": "%",
        "description": "Share of failed calls above which a tool is flagged.",
        "default": 0.1,
        "min": 0.01,
        "max": 0.9,
        "step": 0.01,
    },
    {
        "key": "tool_slow_ms",
        "group": "Tools",
        "label": "Slow tool",
        "unit": "ms",
        "description": "Average tool execution time above which the caller waits too long.",
        "default": 2000,
        "min": 100,
        "max": 30000,
        "step": 100,
    },
    {
        "key": "min_sample",
        "group": "Sampling",
        "label": "Minimum sample",
        "unit": "observations",
        "description": "Observations needed before an average or rate-based rule fires.",
        "default": 3,
        "min": 1,
        "max": 50,
        "step": 1,
    },
]
SPEC_BY_KEY = {s["key"]: s for s in SPEC}
DEFAULTS = {s["key"]: s["default"] for s in SPEC}


def clamp(key: str, value: Any) -> float | int | None:
    spec = SPEC_BY_KEY.get(key)
    if spec is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    number = min(spec["max"], max(spec["min"], number))
    return int(round(number)) if isinstance(spec["default"], int) else round(number, 3)


def normalize(values: dict | None) -> dict:
    """Defaults overlaid with valid, clamped values; the critical latency is
    kept above the warning one."""
    result = dict(DEFAULTS)
    for key, value in (values or {}).items():
        clamped = clamp(key, value)
        if clamped is not None:
            result[key] = clamped
    if result["reply_p50_crit_ms"] <= result["reply_p50_warn_ms"]:
        result["reply_p50_crit_ms"] = result["reply_p50_warn_ms"] + 500
    if result["voice_speed_crit"] >= result["voice_speed_warn"]:
        result["voice_speed_crit"] = round(max(0.5, result["voice_speed_warn"] - 0.3), 3)
    return result


async def load(organization_id: int) -> dict:
    """Stored thresholds state: {values, source, suggestions, suggested_at, model}."""
    from api.db import db_client

    row = await db_client.get_configuration(organization_id, THRESHOLDS_KEY)
    state = dict(row.value) if row and row.value else {}
    state["values"] = normalize(state.get("values"))
    state.setdefault("source", "builtin")
    state.setdefault("suggestions", {})
    return state


async def store(organization_id: int, state: dict) -> dict:
    from api.db import db_client

    state = {**state, "values": normalize(state.get("values"))}
    await db_client.upsert_configuration(organization_id, THRESHOLDS_KEY, state)
    return state


# ------------------------------------------------------- model suggestion


def observed_profile(calls: list[dict]) -> dict:
    """What the calls show, for the model to calibrate on (digested calls)."""
    replies = [t for c in calls for t in c["turns"] if not t["greeting"]]

    def p(values, q):
        if not values:
            return None
        ordered = sorted(values)
        return round(ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1) + 0.5))])

    gaps = []
    for c in calls:
        msgs = [m for m in c["messages"] if m["start"]]
        for prev, nxt in zip(msgs, msgs[1:], strict=False):
            gap = (nxt["start"] - (prev["end"] or prev["start"])).total_seconds()
            if gap > 0:
                gaps.append(gap)
    turns_per_node = []
    for c in calls:
        per: dict = {}
        for m in c["messages"]:
            if m["role"] == "caller":
                per[m["node"]] = per.get(m["node"], 0) + 1
        turns_per_node.extend(per.values())
    agent_msgs = [m for c in calls for m in c["messages"] if m["role"] == "agent"]
    return {
        "calls": len(calls),
        "replies": len(replies),
        "reply_ms": {
            "p50": p([t["total_ms"] for t in replies], 0.5),
            "p90": p([t["total_ms"] for t in replies], 0.9),
        },
        "stage_avg_ms": {
            s: round(sum(t["stages"][s] for t in replies) / len(replies))
            if replies
            else None
            for s in ("endpointing", "transcriber", "llm", "voice")
        },
        "greeting_ms_p50": p(
            [t["total_ms"] for c in calls for t in c["turns"] if t["greeting"]], 0.5
        ),
        "silence_gap_s": {
            "p50": round(median(gaps), 1) if gaps else None,
            "p90": p(gaps, 0.9),
        },
        "caller_turns_per_node": {
            "p50": p(turns_per_node, 0.5),
            "max": max(turns_per_node, default=None),
        },
        "interruption_rate": round(
            sum(1 for m in agent_msgs if m["interrupted"]) / len(agent_msgs), 3
        )
        if agent_msgs
        else None,
    }


SUGGEST_PROMPT = """You calibrate the detection thresholds of an audit of phone voice agents.
The audit flags configuration problems; thresholds must flag what callers would perceive as a
problem for THIS use case, not normal behaviour, and stay useful as the agents improve (do not
simply set them above what is observed). Rely on voice-UX norms (e.g. replies faster than
~1-1.5 s feel natural on the phone, > 3 s feel broken; the reply time here excludes the
end-of-turn wait, a setting of 0.2-1 s judged on its own) and on the agents' purpose (a medical
receptionist and a sales qualifier tolerate different pacing).

You receive: the thresholds (meaning, unit, built-in default, allowed range), the agents
(names, nodes, start of their instructions) and what the recorded calls show.
Rates are fractions (0.25 = 25 %).

Answer with ONLY a JSON object:
{"thresholds": {"<key>": {"value": <number>, "reason": "<one short sentence>"}}}
Give every key. Write the reasons in {language}."""


async def suggest(
    model: dict, agents: list[dict], profile: dict, *, language: str
) -> dict:
    """Ask the analysis model for thresholds; returns {key: {value, reason}} (clamped)."""
    from api.brand.analysis import _extract_json

    payload = {
        "thresholds": [
            {
                k: s[k]
                for k in (
                    "key",
                    "label",
                    "description",
                    "unit",
                    "default",
                    "min",
                    "max",
                )
            }
            for s in SPEC
        ],
        "agents": agents,
        "observed": profile,
    }
    body = {
        "model": model["model"],
        "temperature": 0.2,
        "max_tokens": 4000,
        "messages": [
            {
                "role": "system",
                "content": SUGGEST_PROMPT.replace("{language}", language),
            },
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, default=str),
            },
        ],
        "chat_template_kwargs": {"enable_thinking": False},
    }
    headers = (
        {"Authorization": f"Bearer {model['api_key']}"} if model.get("api_key") else {}
    )
    url = f"{model['base_url'].rstrip('/')}/chat/completions"
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        response = await client.post(url, headers=headers, json=body)
        if response.status_code == 400 and "chat_template_kwargs" in response.text:
            body.pop("chat_template_kwargs")
            response = await client.post(url, headers=headers, json=body)
    if response.status_code >= 400:
        raise RuntimeError(
            f"{url} answered HTTP {response.status_code}: {response.text[:200]}"
        )
    content = response.json()["choices"][0]["message"].get("content") or ""
    raw = (_extract_json(content).get("thresholds") or {}) if content else {}
    suggestions = {}
    for key, item in raw.items():
        value = item.get("value") if isinstance(item, dict) else item
        clamped = clamp(key, value)
        if clamped is not None:
            suggestions[key] = {
                "value": clamped,
                "reason": str(item.get("reason") or "")
                if isinstance(item, dict)
                else "",
            }
    if not suggestions:
        raise RuntimeError("the model returned no usable threshold")
    return suggestions


def agents_context(graphs: dict[int, dict]) -> list[dict]:
    """Agents' purpose for the model: names, nodes and start of instructions."""
    agents = []
    for entry in graphs.values():
        workflow_json = entry.get("workflow_json") or {}
        nodes = workflow_json.get("nodes") or []
        start = next((n for n in nodes if n.get("type") == "startCall"), None)
        agents.append(
            {
                "name": entry.get("workflow_name"),
                "nodes": [
                    f"{(n.get('data') or {}).get('name')} ({n.get('type')})"
                    for n in nodes
                ][:20],
                "instructions_start": ((start or {}).get("data") or {}).get(
                    "prompt", ""
                )[:500],
            }
        )
    return agents


async def suggest_for_organization(
    organization_id: int, *, timezone: str, language: str
) -> dict:
    """Model suggestions from the last 30 days of calls; stores and applies them."""
    from zoneinfo import ZoneInfo

    from api.brand.analysis import resolve_analysis_model, run_rules
    from api.brand.db import get_definition_graphs, get_runs_for_insights
    from api.brand.insights import period_bounds

    model = await resolve_analysis_model(organization_id)
    if model is None:
        raise RuntimeError("No analysis model configured (Models › Analysis).")
    tz = ZoneInfo(timezone)
    start_utc, end_utc = period_bounds(datetime.now(tz).date().isoformat(), 30, tz)
    runs = await get_runs_for_insights(
        organization_id=organization_id, start_utc=start_utc, end_utc=end_utc, limit=500
    )
    graphs = await get_definition_graphs(
        [r["definition_id"] for r in runs if r["definition_id"]],
        organization_id=organization_id,
    )
    _, _, calls = run_rules(runs, graphs)
    suggestions = await suggest(
        model, agents_context(graphs), observed_profile(calls), language=language
    )
    state = await load(organization_id)
    state.update(
        values={k: v["value"] for k, v in suggestions.items()},
        suggestions=suggestions,
        source="model",
        suggested_at=datetime.now(UTC).isoformat(timespec="seconds"),
        model=model["model"],
    )
    return await store(organization_id, state)
