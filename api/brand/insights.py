"""Reporting insights: latency, consumption, conversation quality, tools and
routing aggregated over the calls of a period.

Computed from what each run already stores (``logs.realtime_feedback_events``,
``usage_info``, ``gathered_context``) plus the OxeePhone call-insight events
(``oxee-latency-breakdown``, ``interrupted`` flags). The per-stage latency
logic mirrors ``ui/src/brand/call-detail/model.ts`` (``latencyTurns``).
"""

import ast
import re
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from statistics import mean, median
from typing import Any
from zoneinfo import ZoneInfo

from api.brand.call_insights import LATENCY_BREAKDOWN
from api.services.workflow.workflow_graph import transition_tool_name

SLOW_TURN_MS = 2000
STAGES = (
    "endpointing",
    "transcriber",
    "llm",
    "tools",
    "sentence",
    "voice",
    "transport",
    "other",
)
_ENDPOINTING_KEYS = {"endpointing_wait", "turn_detection", "waiting_for_user"}
_SERVICE = re.compile(r"(STT|TTS|LLM)Service")


def _num(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _ts(iso: Any) -> datetime | None:
    if not isinstance(iso, str) or not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _kind(processor: str) -> str | None:
    match = _SERVICE.search(processor or "")
    return match.group(1).lower() if match else None


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


# ------------------------------------------------------------------ latency


def latency_turn(payload: dict) -> dict:
    """Stages (ms) of one turn; same model as the call-detail Latency tab."""
    stages = dict.fromkeys(STAGES, 0.0)
    turn_end = 0.0
    for c in payload.get("contributions") or []:
        duration, key = _num(c.get("duration_secs")), c.get("key")
        if key in _ENDPOINTING_KEYS:
            stages["endpointing"] += duration * 1000
        elif key == "output_transport":
            stages["transport"] += duration * 1000
        elif key == "transcription":
            stages["transcriber"] += duration * 1000
        if key in _ENDPOINTING_KEYS or key == "transcription":
            turn_end = max(turn_end, _num(c.get("start_time")) + duration)
    ttfb = payload.get("ttfb") or []
    llm = [t for t in ttfb if _kind(t.get("processor", "")) == "llm"]
    tts = [t for t in ttfb if _kind(t.get("processor", "")) == "tts"]
    if not stages["transcriber"]:
        stt = [
            _num(t.get("duration_secs"))
            for t in ttfb
            if _kind(t.get("processor", "")) == "stt"
        ]
        stages["transcriber"] = max(stt, default=0) * 1000
    stages["tools"] = (
        sum(_num(c.get("duration_secs")) for c in payload.get("function_calls") or [])
        * 1000
    )
    aggregation = payload.get("text_aggregation") or {}
    stages["sentence"] = _num(aggregation.get("duration_secs")) * 1000
    first_token = sum(_num(t.get("duration_secs")) for t in llm) * 1000
    first_audio = max(tts, key=lambda t: _num(t.get("start_time")), default=None)
    stages["voice"] = (
        _num(first_audio.get("duration_secs")) * 1000 if first_audio else 0
    )
    if llm and first_audio:
        request = min(_num(t.get("start_time")) for t in llm)
        start = max(request, turn_end or request)
        stages["llm"] = max(
            0.0,
            (_num(first_audio.get("start_time")) - start) * 1000
            - stages["tools"]
            - stages["sentence"],
        )
    else:
        stages["llm"] = first_token
    total = _num(payload.get("total_secs")) * 1000
    named = sum(v for k, v in stages.items() if k != "other")
    stages["other"] = max(0.0, total - named)
    return {
        "greeting": payload.get("measured_from") == "client_connected",
        "total_ms": max(total, named),
        "first_token_ms": first_token,
        "stages": stages,
    }


# -------------------------------------------------------------------- tools


def _tool_failed(result: Any) -> bool:
    data = result
    if isinstance(result, str):
        try:
            data = ast.literal_eval(result)
        except (ValueError, SyntaxError):
            return "error" in result.lower()
    if not isinstance(data, dict):
        return False
    status = str(data.get("status", "")).lower()
    code = data.get("status_code")
    return status in {"error", "failed", "failure", "transfer_failed"} or (
        isinstance(code, int) and code >= 400
    )


# ------------------------------------------------------------------ compute


def compute_insights(
    runs: list[dict], graphs: dict[int, dict], *, tz: ZoneInfo
) -> dict:
    """Aggregate a list of runs (see ``get_runs_for_insights``)."""
    transition_tools: dict[int, dict[str, dict]] = {}
    node_names: dict[int, dict[str, str]] = {}
    for definition_id, entry in graphs.items():
        workflow_json = entry.get("workflow_json") or {}
        node_names[definition_id] = {
            str(n.get("id")): (n.get("data") or {}).get("name") or str(n.get("id"))
            for n in workflow_json.get("nodes") or []
        }
        transition_tools[definition_id] = {
            transition_tool_name((e.get("data") or {}).get("label") or ""): e
            for e in workflow_json.get("edges") or []
            if (e.get("data") or {}).get("label")
        }

    turns: list[dict] = []
    greetings: list[float] = []
    day_latencies: dict[str, list[float]] = defaultdict(list)
    daily: dict[str, dict] = defaultdict(
        lambda: {"calls": 0, "prompt": 0, "completion": 0}
    )
    models: dict[str, dict] = defaultdict(
        lambda: {"calls": 0, "prompt": 0, "completion": 0, "cached": 0}
    )
    tools: dict[str, dict] = defaultdict(
        lambda: {"calls": 0, "errors": 0, "durations": []}
    )
    pathways: Counter = Counter()
    nodes: Counter = Counter()
    end_reasons: Counter = Counter()
    durations: list[float] = []
    turn_counts: list[int] = []
    totals = {
        "prompt": 0,
        "completion": 0,
        "cached": 0,
        "tts_chars": 0,
        "caller_speech": 0.0,
        "agent_speech": 0.0,
    }
    agent_messages = interrupted = calls_with_errors = completed = 0

    for run in runs:
        day = run["created_at"].astimezone(tz).date().isoformat()
        daily[day]["calls"] += 1
        completed += 1 if run["is_completed"] else 0
        usage = run["usage_info"] or {}
        gathered = run["gathered_context"] or {}
        events = (run["logs"] or {}).get("realtime_feedback_events") or []
        tool_map = transition_tools.get(run["definition_id"], {})
        names = node_names.get(run["definition_id"], {})

        duration = _num(usage.get("call_duration_seconds"))
        if duration:
            durations.append(duration)
        if gathered.get("call_status"):
            end_reasons[str(gathered["call_status"])] += 1

        for key, value in (usage.get("llm") or {}).items():
            processor, _, model = key.partition("|||")
            if not isinstance(value, dict):
                continue
            prompt, completion = (
                int(_num(value.get("prompt_tokens"))),
                int(_num(value.get("completion_tokens"))),
            )
            cached = int(_num(value.get("cache_read_input_tokens")))
            label = model or processor
            if processor.startswith("QAAnalysis"):
                label = f"{label} (post-call analysis)"
            models[label]["calls"] += 1
            models[label]["prompt"] += prompt
            models[label]["completion"] += completion
            models[label]["cached"] += cached
            totals["prompt"] += prompt
            totals["completion"] += completion
            totals["cached"] += cached
            daily[day]["prompt"] += prompt
            daily[day]["completion"] += completion
        totals["tts_chars"] += int(
            sum(_num(v) for v in (usage.get("tts") or {}).values())
        )

        user_turns: set = set()
        starts: dict[str, dict] = {}
        had_error = False
        for e in events:
            etype, payload = e.get("type"), e.get("payload") or {}
            if etype in ("rtf-user-transcription", "rtf-bot-text"):
                start, end = (
                    _ts(payload.get("timestamp")),
                    _ts(payload.get("end_timestamp")),
                )
                speech = (
                    (end - start).total_seconds()
                    if start and end and end > start
                    else 0.0
                )
                if etype == "rtf-user-transcription":
                    if payload.get("final") is not False:
                        totals["caller_speech"] += speech
                        user_turns.add(e.get("turn"))
                else:
                    totals["agent_speech"] += speech
                    agent_messages += 1
                    interrupted += 1 if payload.get("interrupted") else 0
            elif etype == LATENCY_BREAKDOWN:
                turn = latency_turn(payload)
                if turn["greeting"]:
                    greetings.append(turn["total_ms"])
                else:
                    turns.append(turn)
                    day_latencies[day].append(turn["total_ms"])
            elif etype == "rtf-function-call-start":
                starts[str(payload.get("tool_call_id"))] = e
            elif etype == "rtf-function-call-end":
                start = starts.get(str(payload.get("tool_call_id")))
                name = str(payload.get("function_name") or "")
                if name in tool_map:
                    continue  # node transition, counted under routing
                tools[name]["calls"] += 1
                tools[name]["errors"] += 1 if _tool_failed(payload.get("result")) else 0
                t0, t1 = _ts((start or {}).get("timestamp")), _ts(e.get("timestamp"))
                if t0 and t1:
                    tools[name]["durations"].append((t1 - t0).total_seconds() * 1000)
            elif etype == "rtf-node-transition":
                node_name = payload.get("node_name") or names.get(
                    str(payload.get("node_id")), ""
                )
                nodes[(run["workflow_name"], node_name)] += 1
                previous = payload.get("previous_node_name")
                if previous:
                    pathways[(run["workflow_name"], previous, node_name)] += 1
            elif etype == "rtf-pipeline-error":
                had_error = True
        if gathered.get("call_status") == "pipeline_error":
            had_error = True
        calls_with_errors += 1 if had_error else 0
        if user_turns:
            turn_counts.append(len(user_turns))

    totals_ms = [t["total_ms"] for t in turns]
    stage_avgs = {
        s: round(mean(t["stages"][s] for t in turns), 1) if turns else 0.0
        for s in STAGES
    }
    first_tokens = [t["first_token_ms"] for t in turns if t["first_token_ms"] > 0]
    prompt_total = totals["prompt"]
    return {
        "calls": {
            "total": len(runs),
            "completed": completed,
            "with_errors": calls_with_errors,
            "avg_duration_secs": round(mean(durations), 1) if durations else None,
            "total_minutes": round(sum(durations) / 60, 1),
            "avg_turns": round(mean(turn_counts), 1) if turn_counts else None,
            "truncated": len(runs) >= 5000,
        },
        "latency": {
            "turns": len(turns),
            "avg_ms": round(mean(totals_ms)) if totals_ms else None,
            "p50_ms": round(median(totals_ms)) if totals_ms else None,
            "p90_ms": round(_percentile(totals_ms, 0.9)) if totals_ms else None,
            "slow_share": round(
                sum(1 for t in totals_ms if t > SLOW_TURN_MS) / len(totals_ms), 3
            )
            if totals_ms
            else None,
            "slow_threshold_ms": SLOW_TURN_MS,
            "greeting_avg_ms": round(mean(greetings)) if greetings else None,
            "llm_first_token_avg_ms": round(mean(first_tokens))
            if first_tokens
            else None,
            "stages": stage_avgs,
        },
        "conversation": {
            "agent_messages": agent_messages,
            "interrupted": interrupted,
            "interruption_rate": round(interrupted / agent_messages, 3)
            if agent_messages
            else None,
            "end_reasons": [
                {"reason": r, "count": c} for r, c in end_reasons.most_common()
            ],
        },
        "usage": {
            "prompt_tokens": prompt_total,
            "completion_tokens": totals["completion"],
            "cached_tokens": totals["cached"],
            "cache_hit_rate": round(totals["cached"] / prompt_total, 3)
            if prompt_total
            else None,
            "tokens_per_call": round((prompt_total + totals["completion"]) / len(runs))
            if runs
            else None,
            "tts_characters": totals["tts_chars"],
            "caller_speech_minutes": round(totals["caller_speech"] / 60, 1),
            "agent_speech_minutes": round(totals["agent_speech"] / 60, 1),
            "models": sorted(
                ({"model": m, **v} for m, v in models.items()),
                key=lambda row: -(row["prompt"] + row["completion"]),
            ),
        },
        "tools": sorted(
            (
                {
                    "name": name,
                    "calls": v["calls"],
                    "errors": v["errors"],
                    "avg_ms": round(mean(v["durations"])) if v["durations"] else None,
                }
                for name, v in tools.items()
            ),
            key=lambda row: -row["calls"],
        ),
        "routing": {
            "pathways": [
                {"workflow": w, "from": f, "to": t, "count": c}
                for (w, f, t), c in pathways.most_common(10)
            ],
            "nodes": [
                {"workflow": w, "name": n, "visits": c}
                for (w, n), c in nodes.most_common(10)
            ],
        },
        "daily": [
            {
                "date": day,
                "calls": daily[day]["calls"],
                "avg_latency_ms": round(mean(day_latencies[day]))
                if day_latencies[day]
                else None,
                "p90_latency_ms": round(_percentile(day_latencies[day], 0.9))
                if day_latencies[day]
                else None,
                "prompt_tokens": daily[day]["prompt"],
                "completion_tokens": daily[day]["completion"],
            }
            for day in sorted(daily)
        ],
    }


def period_bounds(date: str, days: int, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """UTC bounds of ``days`` local days ending on ``date`` (inclusive)."""
    end_day = datetime.strptime(date, "%Y-%m-%d").date()
    start_day = end_day - timedelta(days=days - 1)
    utc = ZoneInfo("UTC")
    return (
        datetime.combine(start_day, time.min, tzinfo=tz).astimezone(utc),
        datetime.combine(end_day, time.max, tzinfo=tz).astimezone(utc),
    )


async def get_insights(
    *,
    organization_id: int,
    date: str,
    days: int,
    timezone: str,
    workflow_id: int | None,
) -> dict:
    from api.brand.db import get_definition_graphs, get_runs_for_insights

    tz = ZoneInfo(timezone)
    start_utc, end_utc = period_bounds(date, days, tz)
    runs = await get_runs_for_insights(
        organization_id=organization_id,
        start_utc=start_utc,
        end_utc=end_utc,
        workflow_id=workflow_id,
    )
    graphs = await get_definition_graphs(
        [r["definition_id"] for r in runs if r["definition_id"]],
        organization_id=organization_id,
    )
    insights = compute_insights(runs, graphs, tz=tz)
    insights["period"] = {
        "start": (end_utc.astimezone(tz).date() - timedelta(days=days - 1)).isoformat(),
        "end": date,
        "days": days,
        "timezone": timezone,
    }
    return insights
