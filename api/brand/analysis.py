"""Configuration analysis: find what to fix in the agents from recorded calls.

Two layers:

1. **Rules** (deterministic, exact numbers): latency per stage and model, dead
   air, time and turns per node, routing loops and ping-pong, transitions
   without a matching pathway, hang-ups right after a transition, pathways
   never taken / nodes never reached, interruptions per node, tool errors and
   slowness, pipeline errors.
2. **Analysis model** (the org's analysis LLM): reviews the rule findings
   together with the agents' pathway conditions and transcript excerpts
   around each transition, judges misrouting, writes an executive summary,
   adds findings the rules cannot see and a recommendation per rule finding.

Reports are stored as organization configurations (``OXEE_ANALYSIS_REPORT:<id>``),
the analysis model under ``OXEE_ANALYSIS_MODEL``.
"""

import json
import re
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from itertools import pairwise
from statistics import mean, median
from typing import Any

import httpx
from loguru import logger

from api.brand.call_insights import LATENCY_BREAKDOWN
from api.brand.insights import _tool_failed, latency_turn
from api.services.workflow.workflow_graph import transition_tool_name

MODEL_KEY = "OXEE_ANALYSIS_MODEL"
REPORT_PREFIX = "OXEE_ANALYSIS_REPORT:"
MAX_REPORTS = 30
STALE_RUNNING_MINUTES = 20

# Detection thresholds: api/brand/analysis_thresholds.py (org-configurable).
MAX_TRANSITIONS_FOR_MODEL = 40
MAX_EXAMPLES = 5

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
RULE_ONLY_CATEGORIES = {"latency", "silence", "tools", "reliability"}


def _ts(iso: Any) -> datetime | None:
    if not isinstance(iso, str) or not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%"


class _Finding:
    """Rule finding builder with a stable id (for model recommendations)."""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(
        self,
        *,
        rule: str,
        severity: str,
        category: str,
        title: str,
        detail: str,
        agent: str | None = None,
        node: str | None = None,
        calls: list | None = None,
        metrics: dict | None = None,
    ) -> None:
        self.items.append(
            {
                "id": f"r{len(self.items) + 1}",
                "source": "rule",
                "rule": rule,
                "severity": severity,
                "category": category,
                "title": title,
                "detail": detail,
                "agent": agent,
                "node": node,
                "calls": sorted({c for c in (calls or []) if c is not None})[
                    :MAX_EXAMPLES
                ],
                "metrics": metrics or {},
                "recommendation": None,
            }
        )


# ------------------------------------------------------------ run digestion


def _graph_index(graphs: dict[int, dict]) -> dict[int, dict]:
    index = {}
    for definition_id, entry in graphs.items():
        workflow_json = entry.get("workflow_json") or {}
        nodes = {str(n.get("id")): n for n in workflow_json.get("nodes") or []}
        edges = []
        for e in workflow_json.get("edges") or []:
            data = e.get("data") or {}
            label = data.get("label") or ""
            edges.append(
                {
                    "id": str(e.get("id")),
                    "source": str(e.get("source")),
                    "target": str(e.get("target")),
                    "label": label,
                    "condition": data.get("condition") or "",
                    "tool": transition_tool_name(label) if label else "",
                }
            )
        index[definition_id] = {
            "workflow_name": entry.get("workflow_name"),
            "names": {
                nid: (n.get("data") or {}).get("name") or nid
                for nid, n in nodes.items()
            },
            "types": {nid: n.get("type") for nid, n in nodes.items()},
            "edges": edges,
            "tools": {e["tool"] for e in edges if e["tool"]},
        }
    return index


def digest_run(run: dict, graph: dict | None) -> dict:
    """One call reduced to what the rules need."""
    events = (run.get("logs") or {}).get("realtime_feedback_events") or []
    gathered = run.get("gathered_context") or {}
    messages, transitions, tools, turns, errors = [], [], [], [], 0
    starts: dict[str, dict] = {}
    for e in events:
        etype, payload, at = (
            e.get("type"),
            e.get("payload") or {},
            _ts(e.get("timestamp")),
        )
        if etype in ("rtf-user-transcription", "rtf-bot-text"):
            if etype == "rtf-user-transcription" and payload.get("final") is False:
                continue
            text = str(payload.get("text") or "").strip()
            if not text:
                continue
            messages.append(
                {
                    "role": "caller" if etype == "rtf-user-transcription" else "agent",
                    "text": text,
                    "start": _ts(payload.get("timestamp")) or at,
                    "end": _ts(payload.get("end_timestamp")),
                    "node": e.get("node_name"),
                    "turn": e.get("turn"),
                    "interrupted": bool(payload.get("interrupted")),
                }
            )
        elif etype == "rtf-node-transition":
            transitions.append(
                {
                    "at": at,
                    "node_id": str(payload.get("node_id") or ""),
                    "node": payload.get("node_name"),
                    "from_id": payload.get("previous_node_id"),
                    "from": payload.get("previous_node_name"),
                }
            )
        elif etype == "rtf-function-call-start":
            starts[str(payload.get("tool_call_id"))] = {
                "at": at,
                "name": payload.get("function_name"),
            }
        elif etype == "rtf-function-call-end":
            start = starts.get(str(payload.get("tool_call_id")), {})
            tools.append(
                {
                    "name": str(
                        payload.get("function_name") or start.get("name") or ""
                    ),
                    "at": start.get("at") or at,
                    "ms": (at - start["at"]).total_seconds() * 1000
                    if at and start.get("at")
                    else None,
                    "failed": _tool_failed(payload.get("result")),
                }
            )
        elif etype == LATENCY_BREAKDOWN:
            turns.append(latency_turn(payload))
        elif etype == "rtf-pipeline-error":
            errors += 1

    # Match each transition with the LLM's transition tool call (same logic as the UI).
    edge_tools = graph["tools"] if graph else set()
    used: set[int] = set()
    for t in transitions:
        t["pathway"] = None
        if not t["from_id"] or not graph:
            continue
        out = [e for e in graph["edges"] if e["source"] == str(t["from_id"])]
        best = None
        for i, call in enumerate(tools):
            edge = next(
                (e for e in out if e["tool"] and e["tool"] == call["name"]), None
            )
            if i in used or not edge or not call["at"] or not t["at"]:
                continue
            gap = abs((call["at"] - t["at"]).total_seconds())
            if gap <= 5 and (best is None or gap < best[0]):
                best = (gap, i, edge)
        if best:
            used.add(best[1])
            t["pathway"] = best[2]

    visits = gathered.get("agent_visits") or []
    runtime = (
        visits[0].get("runtime_configuration")
        if visits and isinstance(visits[0], dict)
        else None
    ) or {}
    ended_at = max(
        [m["end"] or m["start"] for m in messages if m["start"]]
        + [t["at"] for t in transitions if t["at"]],
        default=None,
    )
    return {
        "id": run["id"],
        "workflow_id": run.get("workflow_id"),
        "agent": run.get("workflow_name")
        or (graph or {}).get("workflow_name")
        or f"Agent {run.get('workflow_id')}",
        "definition_id": run.get("definition_id"),
        "status": str(gathered.get("call_status") or ""),
        "messages": sorted(
            messages, key=lambda m: m["start"] or datetime.min.replace(tzinfo=UTC)
        ),
        "transitions": transitions,
        "tools": [t for t in tools if t["name"] not in edge_tools],
        "turns": turns,
        "errors": errors
        + (1 if gathered.get("call_status") == "pipeline_error" else 0),
        "models": {
            k: runtime.get(k)
            for k in ("llm_model", "stt_model", "tts_model")
            if runtime.get(k)
        },
        "ended_at": ended_at,
    }


# ------------------------------------------------------------------- rules


def _latency_rules(f: _Finding, calls: list[dict], th: dict) -> dict:
    stage_warn = {
        "llm": th["llm_stage_warn_ms"],
        "transcriber": th["transcriber_stage_warn_ms"],
        "voice": th["voice_stage_warn_ms"],
        "endpointing": th["endpointing_stage_warn_ms"],
    }
    by_agent: dict[str, list] = defaultdict(list)
    for c in calls:
        for t in c["turns"]:
            by_agent[c["agent"]].append((c, t))
    stats = {}
    for agent, items in by_agent.items():
        replies = [(c, t) for c, t in items if not t["greeting"]]
        greetings = [t["total_ms"] for _, t in items if t["greeting"]]
        models = Counter(
            m for c, _ in items for m in [c["models"].get("llm_model")] if m
        )
        llm_model = models.most_common(1)[0][0] if models else None
        stt = Counter(
            c["models"].get("stt_model")
            for c, _ in items
            if c["models"].get("stt_model")
        )
        tts = Counter(
            c["models"].get("tts_model")
            for c, _ in items
            if c["models"].get("tts_model")
        )
        model_for = {
            "llm": llm_model,
            "transcriber": stt.most_common(1)[0][0] if stt else None,
            "voice": tts.most_common(1)[0][0] if tts else None,
            "endpointing": None,
        }
        if len(replies) >= th["min_sample"]:
            totals = [t["total_ms"] for _, t in replies]
            p50 = median(totals)
            stage_avg = {
                s: mean(t["stages"][s] for _, t in replies) for s in stage_warn
            }
            first_token = [
                t["first_token_ms"] for _, t in replies if t["first_token_ms"]
            ]
            stats[agent] = {
                "replies": len(replies),
                "p50_ms": round(p50),
                "stages": {k: round(v) for k, v in stage_avg.items()},
            }
            slow_calls = [
                c["id"] for c, t in replies if t["total_ms"] > th["reply_p50_warn_ms"]
            ]
            if p50 > th["reply_p50_warn_ms"]:
                worst = max(stage_avg, key=stage_avg.get)
                f.add(
                    rule="reply_latency",
                    severity="critical" if p50 > th["reply_p50_crit_ms"] else "warning",
                    category="latency",
                    title=f"Slow replies: median {p50 / 1000:.1f} s",
                    detail=(
                        f"Median time from the caller falling silent to the agent speaking is {p50:.0f} ms over "
                        f"{len(replies)} replies ({_pct(len(slow_calls and [1 for _, t in replies if t['total_ms'] > th['reply_p50_warn_ms']]) / len(replies))} over "
                        f"{th['reply_p50_warn_ms'] / 1000:.0f} s). Largest stage: {worst} ({stage_avg[worst]:.0f} ms)."
                    ),
                    agent=agent,
                    calls=slow_calls,
                    metrics={
                        "p50_ms": round(p50),
                        "replies": len(replies),
                        **{f"{k}_ms": round(v) for k, v in stage_avg.items()},
                    },
                )
            for stage, limit in stage_warn.items():
                if stage_avg[stage] > limit:
                    model = model_for.get(stage)
                    extra = ""
                    if stage == "llm" and first_token:
                        extra = (
                            f" First token arrives after {mean(first_token):.0f} ms: the rest is spent streaming "
                            "until a complete first sentence (long or verbose openings make it worse)."
                        )
                    f.add(
                        rule=f"stage_{stage}",
                        severity="warning",
                        category="latency",
                        title=f"{stage.capitalize()} stage is slow ({stage_avg[stage]:.0f} ms avg)"
                        + (f" — {model}" if model else ""),
                        detail=f"Average {stage} time per reply is {stage_avg[stage]:.0f} ms (threshold {limit} ms).{extra}",
                        agent=agent,
                        calls=[
                            c["id"] for c, t in replies if t["stages"][stage] > limit
                        ],
                        metrics={
                            "avg_ms": round(stage_avg[stage]),
                            "threshold_ms": limit,
                            "model": model,
                        },
                    )
        if (
            len(greetings) >= th["min_sample"]
            and mean(greetings) > th["greeting_warn_ms"]
        ):
            f.add(
                rule="greeting_latency",
                severity="warning",
                category="latency",
                title=f"Slow greeting ({mean(greetings):.0f} ms after connect)",
                detail="Callers wait before hearing anything after the call connects.",
                agent=agent,
                metrics={"avg_ms": round(mean(greetings))},
            )
    return stats


def _silence_rules(f: _Finding, calls: list[dict], th: dict) -> None:
    by_agent: dict[str, dict] = defaultdict(
        lambda: {"agent_silent": [], "caller_silent": []}
    )
    for c in calls:
        msgs = [m for m in c["messages"] if m["start"]]
        for prev, nxt in pairwise(msgs):
            prev_end = prev["end"] or prev["start"]
            gap = (nxt["start"] - prev_end).total_seconds()
            if gap < th["dead_air_secs"]:
                continue
            key = (
                "agent_silent"
                if prev["role"] == "caller" and nxt["role"] == "agent"
                else "caller_silent"
                if prev["role"] == "agent"
                else None
            )
            if key:
                by_agent[c["agent"]][key].append((c["id"], gap, prev.get("node")))
    for agent, gaps in by_agent.items():
        if gaps["agent_silent"]:
            longest = max(g for _, g, _ in gaps["agent_silent"])
            f.add(
                rule="dead_air_agent",
                severity="warning" if longest < 8 else "critical",
                category="silence",
                title=f"Dead air before the agent answers ({len(gaps['agent_silent'])}×, up to {longest:.0f} s)",
                detail=f"The caller finished speaking and nothing was heard for more than {th['dead_air_secs']:.0f} s before the agent replied.",
                agent=agent,
                node=Counter(n for _, _, n in gaps["agent_silent"] if n).most_common(1)[
                    0
                ][0]
                if any(n for _, _, n in gaps["agent_silent"])
                else None,
                calls=[i for i, _, _ in gaps["agent_silent"]],
                metrics={
                    "occurrences": len(gaps["agent_silent"]),
                    "longest_s": round(longest, 1),
                },
            )
        if len(gaps["caller_silent"]) >= 2:
            longest = max(g for _, g, _ in gaps["caller_silent"])
            f.add(
                rule="dead_air_caller",
                severity="info",
                category="silence",
                title=f"Caller stays silent after the agent speaks ({len(gaps['caller_silent'])}×)",
                detail=(
                    f"Gaps over {th['dead_air_secs']:.0f} s (up to {longest:.0f} s) after the agent spoke: questions may be unclear, "
                    "or the agent does not re-engage the caller."
                ),
                agent=agent,
                calls=[i for i, _, _ in gaps["caller_silent"]],
                metrics={
                    "occurrences": len(gaps["caller_silent"]),
                    "longest_s": round(longest, 1),
                },
            )
    idle = [c for c in calls if c["status"] == "user_idle_max_duration_exceeded"]
    if idle:
        f.add(
            rule="idle_end",
            severity="warning",
            category="silence",
            title=f"{len(idle)} call(s) ended because the caller stayed silent",
            detail="The idle timeout closed the call; check whether the agent asked a clear question before.",
            calls=[c["id"] for c in idle],
            metrics={"calls": len(idle)},
        )


def _node_rules(
    f: _Finding, calls: list[dict], index: dict[int, dict], th: dict
) -> dict:
    per_node: dict[tuple, dict] = defaultdict(
        lambda: {
            "secs": [],
            "turns": [],
            "agent_msgs": 0,
            "interrupted": 0,
            "calls": set(),
        }
    )
    for c in calls:
        tr = [t for t in c["transitions"] if t["at"]]
        for i, t in enumerate(tr):
            end = tr[i + 1]["at"] if i + 1 < len(tr) else c["ended_at"]
            if end:
                per_node[(c["agent"], t["node"])]["secs"].append(
                    (end - t["at"]).total_seconds()
                )
            per_node[(c["agent"], t["node"])]["calls"].add(c["id"])
        turns_in_node: Counter = Counter()
        for m in c["messages"]:
            if m["role"] == "caller":
                turns_in_node[m["node"]] += 1
            else:
                per_node[(c["agent"], m["node"])]["agent_msgs"] += 1
                per_node[(c["agent"], m["node"])]["interrupted"] += (
                    1 if m["interrupted"] else 0
                )
        for node, n in turns_in_node.items():
            per_node[(c["agent"], node)]["turns"].append((n, c["id"]))

    stats = {}
    for (agent, node), v in per_node.items():
        if not node:
            continue
        avg_secs = mean(v["secs"]) if v["secs"] else 0
        max_turns = max((n for n, _ in v["turns"]), default=0)
        stats[f"{agent} / {node}"] = {
            "visits": len(v["secs"]),
            "avg_secs": round(avg_secs, 1),
            "max_caller_turns": max_turns,
        }
        if max_turns >= th["node_turns_warn"]:
            f.add(
                rule="node_stuck",
                severity="warning",
                category="flow",
                title=f"Conversation stalls in “{node}” (up to {max_turns} caller turns)",
                detail=(
                    "Many exchanges happen without leaving this node: its goal may be unclear, or no outgoing "
                    "pathway condition matches what callers say."
                ),
                agent=agent,
                node=node,
                calls=[i for n, i in v["turns"] if n >= th["node_turns_warn"]],
                metrics={"max_caller_turns": max_turns},
            )
        elif len(v["secs"]) >= th["min_sample"] and avg_secs > th["node_secs_warn"]:
            f.add(
                rule="node_time",
                severity="info",
                category="flow",
                title=f"Long time spent in “{node}” ({avg_secs:.0f} s on average)",
                detail="Check that this node collects only what it needs and moves on.",
                agent=agent,
                node=node,
                calls=list(v["calls"]),
                metrics={"avg_secs": round(avg_secs)},
            )
        if (
            v["agent_msgs"] >= th["min_sample"] * 2
            and v["interrupted"] / v["agent_msgs"] > th["interruption_rate_warn"]
        ):
            rate = v["interrupted"] / v["agent_msgs"]
            f.add(
                rule="interruptions",
                severity="warning",
                category="conversation",
                title=f"Callers often interrupt the agent in “{node}” ({_pct(rate)})",
                detail=(
                    "The agent's messages are frequently cut off: they may be too long, repeat information, "
                    "or ask several questions at once."
                ),
                agent=agent,
                node=node,
                calls=list(v["calls"]),
                metrics={
                    "interrupted": v["interrupted"],
                    "agent_messages": v["agent_msgs"],
                },
            )
    return stats


def _routing_rules(
    f: _Finding, calls: list[dict], index: dict[int, dict], th: dict
) -> None:
    loops, ping_pong, unmatched, early_hangups = [], [], [], []
    taken: dict[int, Counter] = defaultdict(Counter)
    reached: dict[int, set] = defaultdict(set)
    calls_per_def: Counter = Counter()
    for c in calls:
        calls_per_def[c["definition_id"]] += 1
        tr = [t for t in c["transitions"] if t["at"]]
        visits = Counter(t["node"] for t in tr)
        for node, n in visits.items():
            if n >= 3:
                loops.append((c, node, n))
        for a, b in pairwise(tr):
            if (
                a["from"]
                and b["node"] == a["from"]
                and (b["at"] - a["at"]).total_seconds() <= th["ping_pong_secs"]
            ):
                ping_pong.append((c, a["from"], a["node"]))
        for t in tr:
            reached[c["definition_id"]].add(t["node_id"])
            if t["from_id"]:
                if t["pathway"]:
                    taken[c["definition_id"]][t["pathway"]["id"]] += 1
                elif c["definition_id"] in index:
                    unmatched.append((c, t))
        graph = index.get(c["definition_id"])
        if (
            tr
            and c["status"] in ("user_hangup", "user_idle_max_duration_exceeded")
            and graph
        ):
            last = tr[-1]
            if (
                graph["types"].get(last["node_id"]) != "endCall"
                and last["from_id"]
                and c["ended_at"]
            ):
                if (c["ended_at"] - last["at"]).total_seconds() <= th[
                    "hangup_after_transition_secs"
                ]:
                    early_hangups.append((c, last))
    if loops:
        f.add(
            rule="routing_loop",
            severity="critical",
            category="routing",
            title=f"Routing loop: node revisited 3+ times ({len(loops)} call(s))",
            detail="; ".join(
                sorted({f"“{node}” ×{n} in {c['agent']}" for c, node, n in loops})
            )[:400]
            + ". Pathway conditions probably overlap, sending the call back and forth.",
            agent=loops[0][0]["agent"],
            node=loops[0][1],
            calls=[c["id"] for c, _, _ in loops],
        )
    if ping_pong:
        pairs = Counter((c["agent"], a, b) for c, a, b in ping_pong)
        (agent, a, b), n = pairs.most_common(1)[0]
        f.add(
            rule="ping_pong",
            severity="warning",
            category="routing",
            title=f"Back-and-forth routing “{a}” ⇄ “{b}” ({n}×)",
            detail=(
                f"The call went {a} → {b} and back within {th['ping_pong_secs']:.0f} s: the move to “{b}” was likely premature "
                "or its outgoing condition fires too easily."
            ),
            agent=agent,
            node=b,
            calls=[c["id"] for c, _, _ in ping_pong],
        )
    if unmatched:
        f.add(
            rule="unmatched_transition",
            severity="info",
            category="routing",
            title=f"{len(unmatched)} transition(s) without a matching pathway",
            detail="The node changed but no pathway decision was recorded (engine-driven move or graph edited since the call).",
            calls=[c["id"] for c, _ in unmatched],
        )
    if early_hangups:
        nodes = Counter((c["agent"], t["node"]) for c, t in early_hangups)
        (agent, node), n = nodes.most_common(1)[0]
        f.add(
            rule="hangup_after_transition",
            severity="warning",
            category="routing",
            title=f"Callers hang up right after reaching “{node}” ({n}×)",
            detail=(
                f"The call ended within {th['hangup_after_transition_secs']:.0f} s of entering this node without reaching an end node: "
                "the routing may be wrong or the node's opening confusing."
            ),
            agent=agent,
            node=node,
            calls=[c["id"] for c, _ in early_hangups],
        )
    for definition_id, graph in index.items():
        if calls_per_def[definition_id] < 5:
            continue  # not enough calls to call a pathway unused
        never = [e for e in graph["edges"] if e["id"] not in taken[definition_id]]
        unreached = [
            graph["names"][n]
            for n, t in graph["types"].items()
            if t not in ("globalNode", "trigger", "webhook", "qa")
            and n not in reached[definition_id]
        ]
        if never:
            f.add(
                rule="pathway_never_taken",
                severity="info",
                category="routing",
                title=f"{len(never)} pathway(s) never taken in {graph['workflow_name']}",
                detail="; ".join(
                    f"{graph['names'].get(e['source'])} → {graph['names'].get(e['target'])} (“{e['label']}”)"
                    for e in never
                )[:500]
                + ". Either callers never need them or their conditions never match.",
                agent=graph["workflow_name"],
                metrics={"calls": calls_per_def[definition_id]},
            )
        if unreached:
            f.add(
                rule="node_unreached",
                severity="info",
                category="routing",
                title=f"Node(s) never reached in {graph['workflow_name']}: {', '.join(unreached)[:120]}",
                detail="No call reached these nodes in the period.",
                agent=graph["workflow_name"],
            )


def _tool_rules(f: _Finding, calls: list[dict], th: dict) -> None:
    per_tool: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "failed": 0, "ms": [], "calls": set(), "failed_calls": set()}
    )
    for c in calls:
        for t in c["tools"]:
            v = per_tool[t["name"]]
            v["n"] += 1
            v["calls"].add(c["id"])
            if t["failed"]:
                v["failed"] += 1
                v["failed_calls"].add(c["id"])
            if t["ms"] is not None:
                v["ms"].append(t["ms"])
    for name, v in per_tool.items():
        if v["failed"] and v["failed"] / v["n"] >= th["tool_error_rate_warn"]:
            f.add(
                rule="tool_errors",
                severity="critical" if v["failed"] / v["n"] >= 0.3 else "warning",
                category="tools",
                title=f"Tool “{name}” fails {_pct(v['failed'] / v['n'])} of the time",
                detail=f"{v['failed']} of {v['n']} calls returned an error.",
                calls=list(v["failed_calls"]),
                metrics={"calls": v["n"], "errors": v["failed"]},
            )
        if v["ms"] and mean(v["ms"]) > th["tool_slow_ms"]:
            f.add(
                rule="tool_slow",
                severity="warning",
                category="tools",
                title=f"Tool “{name}” is slow ({mean(v['ms']):.0f} ms on average)",
                detail="The caller waits while the tool runs; consider a filler sentence or a faster endpoint.",
                calls=list(v["calls"]),
                metrics={"avg_ms": round(mean(v["ms"]))},
            )


def run_rules(
    runs: list[dict], graphs: dict[int, dict], thresholds: dict | None = None
) -> tuple[list[dict], dict, list[dict]]:
    """Apply every rule. Returns (findings, stats, digested calls).

    ``thresholds`` are the organization's values (missing ones fall back to
    the built-in defaults of ``analysis_thresholds``).
    """
    from api.brand.analysis_thresholds import normalize

    th = normalize(thresholds)
    index = _graph_index(graphs)
    calls = [digest_run(r, index.get(r.get("definition_id"))) for r in runs]
    f = _Finding()
    latency = _latency_rules(f, calls, th)
    _silence_rules(f, calls, th)
    nodes = _node_rules(f, calls, index, th)
    _routing_rules(f, calls, index, th)
    _tool_rules(f, calls, th)
    errored = [c for c in calls if c["errors"]]
    if errored:
        f.add(
            rule="pipeline_errors",
            severity="critical"
            if len(errored) / max(1, len(calls)) > 0.1
            else "warning",
            category="reliability",
            title=f"{len(errored)} call(s) hit a pipeline error",
            detail="A service failed during the call (model endpoint, transport...). See the call's Events tab.",
            calls=[c["id"] for c in errored],
            metrics={"calls": len(errored)},
        )
    findings = sorted(f.items, key=lambda x: SEVERITY_ORDER[x["severity"]])
    stats = {"calls": len(calls), "latency_by_agent": latency, "nodes": nodes}
    return findings, stats, calls


# ------------------------------------------------------------ model review


def transition_samples(calls: list[dict], index: dict[int, dict]) -> list[dict]:
    """Transitions with their pathway condition and what was said around them."""
    samples = []
    for c in calls:
        msgs = c["messages"]
        for t in c["transitions"]:
            if not t["from_id"] or not t["at"]:
                continue
            before = [m for m in msgs if m["start"] and m["start"] <= t["at"]][-3:]
            after = [m for m in msgs if m["start"] and m["start"] > t["at"]][:2]
            graph = index.get(c["definition_id"]) or {}
            alternatives = [
                {
                    "to": graph.get("names", {}).get(e["target"]),
                    "condition": e["condition"],
                }
                for e in graph.get("edges", [])
                if e["source"] == str(t["from_id"])
            ]
            samples.append(
                {
                    "call": c["id"],
                    "agent": c["agent"],
                    "from": t["from"],
                    "to": t["node"],
                    "pathway_condition": (t["pathway"] or {}).get("condition"),
                    "other_pathways": [a for a in alternatives if a["to"] != t["node"]],
                    "before": [f"{m['role']}: {m['text']}" for m in before],
                    "after": [f"{m['role']}: {m['text']}" for m in after],
                }
            )
    return samples[:MAX_TRANSITIONS_FOR_MODEL]


SYSTEM_PROMPT = """You audit phone voice agents built as graphs of nodes. Each pathway between nodes has a
condition; the agent's LLM moves the call along a pathway when it judges the condition met.
You receive (1) findings computed by rules with exact numbers, (2) aggregate statistics, and
(3) samples of routing decisions with what the caller and agent said around them.

Your job, strictly grounded in the data (never invent numbers or calls):
- "summary": a short executive summary (3-5 sentences) of the most important problems.
- "rule_findings": for EACH rule finding id, its title and detail rewritten in {language}, keeping
  every number, unit, name and quoted text exactly as given, plus one concrete recommendation
  (what to change in the agent: prompt, pathway condition, node design, model/endpoint, timeout...).
- "findings": ONLY problems the rules did not already report. Review the routing samples: flag
  misrouting (the caller's words did not satisfy the pathway condition, or another pathway fitted
  better), premature or missing transitions, and prompt or conversation-design issues visible in
  the transcripts. Never restate a rule finding here. Cite call ids. An empty list is fine.

Answer with ONLY a JSON object:
{"summary": "...",
 "rule_findings": {"<rule finding id>": {"title": "...", "detail": "...", "recommendation": "..."}},
 "findings": [{"severity": "critical|warning|info", "category": "routing|conversation|prompt|other",
               "title": "...", "detail": "...", "recommendation": "...", "agent": "...", "node": "...",
               "calls": [<call ids>]}]}
Write every text in {language}."""


def _extract_json(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object in the model answer")
    return json.loads(text[start : end + 1])


async def review_with_model(
    model: dict,
    findings: list[dict],
    stats: dict,
    samples: list[dict],
    *,
    language: str = "English",
) -> dict:
    """Ask the analysis model; returns {summary, recommendations, findings}."""
    payload = {
        "rule_findings": [
            {
                k: f[k]
                for k in (
                    "id",
                    "severity",
                    "category",
                    "title",
                    "detail",
                    "agent",
                    "node",
                    "calls",
                    "metrics",
                )
            }
            for f in findings
        ],
        "statistics": stats,
        "routing_samples": samples,
    }
    headers = (
        {"Authorization": f"Bearer {model['api_key']}"} if model.get("api_key") else {}
    )
    body = {
        "model": model["model"],
        "temperature": 0.2,
        "max_tokens": 6000,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT.replace("{language}", language),
            },
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, default=str),
            },
        ],
        # Reasoning models (e.g. Qwen3 on vLLM) otherwise spend the whole token
        # budget thinking over a payload this size and never write the answer.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    url = f"{model['base_url'].rstrip('/')}/chat/completions"
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
        response = await client.post(url, headers=headers, json=body)
        if response.status_code == 400 and "chat_template_kwargs" in response.text:
            body.pop("chat_template_kwargs")  # server without that option
            response = await client.post(url, headers=headers, json=body)
    if response.status_code >= 400:
        raise RuntimeError(
            f"{url} answered HTTP {response.status_code}: {response.text[:200]}"
        )
    data = response.json()
    choice = data["choices"][0]
    content = choice["message"].get("content") or ""
    if not content.strip() and choice.get("finish_reason") == "length":
        raise RuntimeError(
            "the model used its whole token budget reasoning without answering "
            "(choose a non-reasoning model or one that can disable thinking)"
        )
    result = _extract_json(content)
    usage = data.get("usage") or {}
    return {
        "summary": str(result.get("summary") or ""),
        "rule_findings": {
            str(k): v
            for k, v in (result.get("rule_findings") or {}).items()
            if isinstance(v, dict)
        },
        "findings": [
            {
                "id": f"m{i + 1}",
                "source": "model",
                "rule": None,
                "severity": x.get("severity")
                if x.get("severity") in SEVERITY_ORDER
                else "info",
                "category": str(x.get("category") or "other"),
                "title": str(x.get("title") or ""),
                "detail": str(x.get("detail") or ""),
                "recommendation": x.get("recommendation"),
                "agent": x.get("agent"),
                "node": x.get("node"),
                "calls": [c for c in (x.get("calls") or []) if isinstance(c, int)][
                    :MAX_EXAMPLES
                ],
                "metrics": {},
            }
            for i, x in enumerate(result.get("findings") or [])
            if isinstance(x, dict)
            and x.get("title")
            # the rules own these categories, with exact numbers
            and str(x.get("category") or "").lower() not in RULE_ONLY_CATEGORIES
        ],
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        },
    }


# ----------------------------------------------------------- orchestration


async def resolve_analysis_model(organization_id: int) -> dict | None:
    """The analysis model: its own endpoint, or the org's LLM configuration."""
    from api.db import db_client
    from api.services.configuration.ai_model_configuration import (
        get_resolved_ai_model_configuration,
    )

    row = await db_client.get_configuration(organization_id, MODEL_KEY)
    cfg = (row.value if row else None) or {"same_as_llm": True}
    if not cfg.get("same_as_llm", True) and cfg.get("base_url") and cfg.get("model"):
        return {
            "base_url": cfg["base_url"],
            "api_key": cfg.get("api_key"),
            "model": cfg["model"],
            "source": "analysis",
        }
    llm = (
        await get_resolved_ai_model_configuration(organization_id=organization_id)
    ).effective.llm
    if llm is None or not getattr(llm, "base_url", None):
        return None
    keys = llm.get_all_api_keys()
    return {
        "base_url": llm.base_url,
        "api_key": keys[0] if keys else None,
        "model": llm.model,
        "source": "llm",
    }


async def run_analysis(
    report_id: str,
    *,
    organization_id: int,
    date: str,
    days: int,
    timezone: str,
    workflow_id: int | None,
    language: str,
) -> None:
    """Background job: rules, then model review; stores progress in the report."""
    from zoneinfo import ZoneInfo

    from api.brand.db import get_definition_graphs, get_runs_for_insights
    from api.brand.insights import period_bounds

    async def save(**changes):
        report = await get_report(organization_id, report_id) or {}
        report.update(changes)
        await _store_report(organization_id, report)

    try:
        tz = ZoneInfo(timezone)
        start_utc, end_utc = period_bounds(date, days, tz)
        runs = await get_runs_for_insights(
            organization_id=organization_id,
            start_utc=start_utc,
            end_utc=end_utc,
            workflow_id=workflow_id,
            limit=1000,
        )
        graphs = await get_definition_graphs(
            [r["definition_id"] for r in runs if r["definition_id"]],
            organization_id=organization_id,
        )
        from api.brand.analysis_thresholds import load as load_thresholds

        thresholds = await load_thresholds(organization_id)
        await save(
            thresholds={
                "values": thresholds["values"],
                "source": thresholds["source"],
                "model": thresholds.get("model"),
            }
        )
        findings, stats, calls = run_rules(runs, graphs, thresholds["values"])
        await save(
            status="reviewing",
            findings=findings,
            stats=stats,
            calls_analyzed=len(runs),
            # call id -> agent (workflow) id, for links to the call-detail page
            call_links={str(r["id"]): r["workflow_id"] for r in runs},
        )
        if not runs:
            await save(
                status="done", summary="No calls in this period.", finished_at=_now()
            )
            return
        model = await resolve_analysis_model(organization_id)
        if model is None:
            await save(
                status="done",
                finished_at=_now(),
                model_error="No analysis model configured (Models > Analysis); rule findings only.",
            )
            return
        try:
            review = await review_with_model(
                model,
                findings,
                stats,
                transition_samples(calls, _graph_index(graphs)),
                language=language,
            )
        except Exception as e:  # the rules are still useful without the model
            logger.warning(f"Analysis model review failed: {e}")
            await save(
                status="done",
                finished_at=_now(),
                model=model["model"],
                model_error=str(e)[:300],
            )
            return
        for finding in findings:
            rewrite = review["rule_findings"].get(finding["id"]) or {}
            finding["recommendation"] = rewrite.get("recommendation") or None
            if language != "English" and rewrite.get("title"):
                # keep the rule's own text for reference; show the translation
                finding["original"] = {
                    "title": finding["title"],
                    "detail": finding["detail"],
                }
                finding["title"] = str(rewrite["title"])
                finding["detail"] = str(rewrite.get("detail") or finding["detail"])
        merged = sorted(
            findings + review["findings"], key=lambda x: SEVERITY_ORDER[x["severity"]]
        )
        await save(
            status="done",
            finished_at=_now(),
            findings=merged,
            summary=review["summary"],
            model=model["model"],
            model_usage=review["usage"],
        )
    except Exception as e:
        logger.exception("Analysis failed")
        await save(status="failed", finished_at=_now(), error=str(e)[:300])


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_report(
    *,
    date: str,
    days: int,
    timezone: str,
    workflow_id: int | None,
    created_by: str | None,
) -> dict:
    return {
        "id": uuid.uuid4().hex[:12],
        "status": "running",
        "created_at": _now(),
        "finished_at": None,
        "params": {
            "date": date,
            "days": days,
            "timezone": timezone,
            "workflow_id": workflow_id,
        },
        "created_by": created_by,
        "summary": None,
        "findings": [],
        "stats": {},
        "calls_analyzed": None,
        "model": None,
        "model_error": None,
        "error": None,
    }


async def _store_report(organization_id: int, report: dict) -> None:
    from api.db import db_client

    await db_client.upsert_configuration(
        organization_id, REPORT_PREFIX + report["id"], report
    )


async def get_report(organization_id: int, report_id: str) -> dict | None:
    from api.db import db_client

    row = await db_client.get_configuration(organization_id, REPORT_PREFIX + report_id)
    report = dict(row.value) if row and row.value else None
    if report and report.get("status") in ("running", "reviewing"):
        started = _ts(report.get("created_at"))
        if (
            started
            and (datetime.now(UTC) - started).total_seconds()
            > STALE_RUNNING_MINUTES * 60
        ):
            report["status"] = "failed"
            report["error"] = "Interrupted (the API restarted during the analysis)."
    return report


async def create_report(
    user: Any,
    *,
    date: str,
    days: int,
    timezone: str,
    workflow_id: int | None,
    language: str,
) -> tuple[dict, dict]:
    """Store a new (running) report; returns it and the ``run_analysis`` kwargs.

    Raises ValueError on invalid parameters. Keeps the MAX_REPORTS newest.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from api.brand.db import delete_configuration, list_configurations_by_prefix

    if days not in (1, 7, 30):
        raise ValueError("days must be 1, 7 or 30")
    try:
        ZoneInfo(timezone)
        datetime.strptime(date, "%Y-%m-%d")
    except (ValueError, ZoneInfoNotFoundError) as e:
        raise ValueError(str(e)) from e
    organization_id = user.selected_organization_id
    existing = await list_configurations_by_prefix(
        organization_id, REPORT_PREFIX, limit=200
    )
    for old in existing[MAX_REPORTS - 1 :]:
        await delete_configuration(organization_id, REPORT_PREFIX + old["id"])
    report = new_report(
        date=date,
        days=days,
        timezone=timezone,
        workflow_id=workflow_id,
        created_by=str(user.provider_id),
    )
    await _store_report(organization_id, report)
    return report, {
        "organization_id": organization_id,
        "date": date,
        "days": days,
        "timezone": timezone,
        "workflow_id": workflow_id,
        "language": language,
    }
