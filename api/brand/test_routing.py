"""Route of an end-to-end test call through several agents, and its routing
score.

An E2E test call can be handed from agent to agent. As text, every agent
plays in its own run (``test_runs._play_text`` segments); by phone, one run
holds the whole call and the agents' visits (``gathered_context.agent_visits``).
Either way the route is a list of ``{"agent", "workflow_id", "nodes"}``.

The routing score (1-5) checks that the caller reached the right agent at the
right moment: whether the expected agent ended the call, loops between agents,
handoffs beyond the expected route, and the judge's view of each handoff.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _when(value: Any) -> datetime | None:
    from datetime import UTC

    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _dedup(nodes: list[str]) -> list[str]:
    out: list[str] = []
    for n in nodes:
        if n and (not out or out[-1] != n):
            out.append(n)
    return out


def route_of_run(run: dict) -> list[dict]:
    """The agents one run went through (phone calls: visits of the call)."""
    from api.brand.analysis import digest_run

    transitions = digest_run(run, None)["transitions"]
    visits = (run.get("gathered_context") or {}).get("agent_visits") or []
    if not visits:
        return [
            {
                "agent": run.get("workflow_name"),
                "workflow_id": run.get("workflow_id"),
                "nodes": _dedup([t.get("node") or t.get("node_id") for t in transitions]),
            }
        ]
    route = [
        {
            "agent": v.get("workflow_name"),
            "workflow_id": v.get("workflow_id"),
            "entered": _when(v.get("entered_at")),
            "nodes": [],
        }
        for v in visits
    ]
    for t in transitions:
        at = _when(t.get("at"))
        segment = route[0]
        for r in route:
            if at and r["entered"] and r["entered"] <= at:
                segment = r
        segment["nodes"].append(t.get("node") or t.get("node_id"))
    return [
        {"agent": r["agent"], "workflow_id": r["workflow_id"], "nodes": _dedup(r["nodes"])}
        for r in route
    ]


def combine_metrics(parts: list[dict]) -> dict:
    """Metrics of a call played in several runs (one per agent, text E2E)."""
    first, last = parts[0], parts[-1]
    combined = dict(first)
    combined.update(
        duration_seconds=round(sum(p.get("duration_seconds") or 0 for p in parts), 1),
        caller_turns=sum(p.get("caller_turns") or 0 for p in parts),
        agent_turns=sum(p.get("agent_turns") or 0 for p in parts),
        interruptions=sum(p.get("interruptions") or 0 for p in parts),
        tools=[t for p in parts for t in p.get("tools") or []],
        path=[n for p in parts for n in p.get("path") or []],
        path_ids=list(first.get("path_ids") or []),
        edges=list(first.get("edges") or []),
        end_node=last.get("end_node"),
        end_status=last.get("end_status"),
        extracted_variables={
            k: v for p in parts for k, v in (p.get("extracted_variables") or {}).items()
        },
        errors=sum(p.get("errors") or 0 for p in parts),
        transfer=last.get("transfer"),
    )
    return combined


def _same(a: Any, b: Any) -> bool:
    from api.brand.test_runs import _same as same

    return same(a, b)


def routing_grade(scenario: dict, route: list[dict], judge: dict | None) -> dict:
    """Routing score of an E2E test call: what the route shows, then the
    judge's view of the handoffs."""
    agents = [r.get("agent") for r in route if r.get("agent")]
    expected = scenario.get("expected_agent")
    expected_route = [a for a in scenario.get("expected_route") or [] if a]
    final = agents[-1] if agents else None
    reached = _same(final, expected) if expected else None
    loops = len(agents) != len({a.lower() for a in agents})
    extra = max(0, len(agents) - max(len(expected_route), 1)) if expected_route else 0

    facts = 5
    if reached is False:
        facts = 1
    if loops:
        facts -= 1
    facts -= extra
    facts = max(1, facts)

    judged = None
    if isinstance(judge, dict) and isinstance(judge.get("score"), (int, float)):
        judged = max(1, min(5, int(judge["score"])))
    score = (facts + judged) / 2 if judged is not None else float(facts)
    if reached is False:
        score = min(score, 2.0)
    return {
        "score": round(score, 2),
        "route": agents,
        "expected_agent": expected,
        "reached": reached,
        "loops": loops,
        "extra_handoffs": extra,
        "judge": {
            "score": judged,
            "evidence": str((judge or {}).get("evidence") or "")[:400],
            "handoffs": [
                {
                    "to": str(h.get("to") or ""),
                    "justified": bool(h.get("justified")),
                    "evidence": str(h.get("evidence") or "")[:300],
                }
                for h in (judge or {}).get("handoffs") or []
                if isinstance(h, dict)
            ][:6],
        }
        if judge
        else None,
    }
