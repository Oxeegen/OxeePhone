"""OxeePhone: end-to-end test campaigns (real handoffs, routing score)."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from api.brand import test_calls as calls
from api.brand import test_routing as routing
from api.brand import test_runs as runs


def test_routing_grade():
    scenario = {"expected_agent": "Facturation", "expected_route": ["Accueil", "Facturation"]}
    good = routing.routing_grade(
        scenario,
        [{"agent": "Accueil"}, {"agent": "Facturation"}],
        {"score": 5, "evidence": "Transfert justifié", "handoffs": [{"to": "Facturation", "justified": True}]},
    )
    assert good["score"] == 5.0 and good["reached"] is True and good["route"] == ["Accueil", "Facturation"]
    wrong = routing.routing_grade(scenario, [{"agent": "Accueil"}, {"agent": "Urgences"}], {"score": 4})
    assert wrong["reached"] is False and wrong["score"] <= 2
    loop = routing.routing_grade(scenario, [{"agent": "Accueil"}, {"agent": "Facturation"}, {"agent": "Accueil"}, {"agent": "Facturation"}], None)
    assert loop["loops"] and loop["extra_handoffs"] == 2 and loop["score"] == 2.0
    stay = routing.routing_grade({"expected_agent": "Accueil"}, [{"agent": "Accueil"}], None)
    assert stay["score"] == 5.0


def test_route_of_a_phone_call_follows_the_agent_visits():
    t0 = datetime(2026, 10, 16, 10, 0, tzinfo=UTC).timestamp()
    def ev(sec, node):
        return {"type": "rtf-node-transition", "timestamp": datetime.fromtimestamp(t0 + sec, UTC).isoformat(),
                "payload": {"node_id": node, "node_name": node}}
    run = {
        "id": 1, "workflow_name": "Accueil", "workflow_id": 1,
        "logs": {"realtime_feedback_events": [ev(1, "Bienvenue"), ev(20, "Orientation"), ev(40, "Facturation start"), ev(60, "Remboursement")]},
        "gathered_context": {"agent_visits": [
            {"workflow_name": "Accueil", "workflow_id": 1, "entered_at": t0},
            {"workflow_name": "Facturation", "workflow_id": 2, "entered_at": t0 + 35},
        ]},
    }
    route = routing.route_of_run(run)
    assert [r["agent"] for r in route] == ["Accueil", "Facturation"]
    assert route[0]["nodes"] == ["Bienvenue", "Orientation"] and route[1]["nodes"] == ["Facturation start", "Remboursement"]


def test_metrics_of_the_segments_are_combined():
    a = {"duration_seconds": 30, "caller_turns": 3, "agent_turns": 3, "interruptions": 0, "tools": [{"name": "x"}],
         "path": ["A1", "A2"], "end_node": "A2", "end_status": "completed", "extracted_variables": {"nom": "Paul"}, "errors": 0}
    b = {"duration_seconds": 20, "caller_turns": 2, "agent_turns": 2, "interruptions": 1, "tools": [],
         "path": ["B1"], "end_node": "B1", "end_status": "completed", "extracted_variables": {"motif": "facture"}, "errors": 0}
    m = routing.combine_metrics([a, b])
    assert m["duration_seconds"] == 50 and m["agent_turns"] == 5 and m["path"] == ["A1", "A2", "B1"]
    assert m["end_node"] == "B1" and m["extracted_variables"] == {"nom": "Paul", "motif": "facture"}


def test_expected_agent_is_checked():
    metrics = {"route": [{"agent": "Accueil"}, {"agent": "Facturation"}], "final_agent": "Facturation", "tools": []}
    checks = runs.deterministic_checks({"expected_agent": "Facturation"}, metrics)
    assert checks[0]["kind"] == "route" and checks[0]["pass"] and "Accueil → Facturation" in checks[0]["detail"]
    assert runs.deterministic_checks({"expected_agent": "Facturation"}, {"tools": []}) == []  # unit: no route


class _Engine:
    def __init__(self, test):
        self._call_context_vars = {"oxee_test": test} if test is not None else {}
        self._workflow_run_id = 5
        self.recorded = {}

    def record_context(self, values):
        self.recorded.update(values)


@pytest.mark.asyncio
async def test_agent_transfer_plan(monkeypatch):
    from api.db import db_client

    mode = {"value": "textchat"}

    async def run_by_id(run_id):
        return SimpleNamespace(mode=mode["value"])

    monkeypatch.setattr(db_client, "get_workflow_run_by_id", run_by_id)
    assert await calls.agent_transfer_plan(_Engine({"mode": "unit", "tools_mode": "simulated"})) == "simulate"
    assert await calls.agent_transfer_plan(_Engine({"mode": "unit", "tools_mode": "real"})) is None
    assert await calls.agent_transfer_plan(_Engine({"mode": "e2e"})) == "handoff"
    mode["value"] = "ari"
    assert await calls.agent_transfer_plan(_Engine({"mode": "e2e"})) == "real"
    assert await calls.agent_transfer_plan(_Engine(None)) is None
    engine = _Engine({"mode": "e2e"})
    calls.record_handoff(engine, SimpleNamespace(name="facturation", definition={"config": {"workflow_id": 9}}), {})
    assert engine.recorded[calls.HANDOFF_CONTEXT_KEY]["destination_workflow_id"] == 9


def test_routing_report_and_comparison():
    done = lambda r: {"status": "done", "routing": r}
    calls_ = [
        done({"score": 5.0, "reached": True, "loops": False, "route": ["Accueil", "Facturation"]}),
        done({"score": 2.0, "reached": False, "loops": True, "route": ["Accueil", "Urgences", "Accueil"]}),
        {"status": "done", "routing": None},
    ]
    report = runs.routing_report(calls_)
    assert report["routing_score"] == 3.5 and report["routing"]["reach_rate"] == 0.5
    assert report["routing"]["handoffs_per_call"] == 1.5
    assert runs.routing_report([{"status": "done"}]) == {"routing_score": None, "routing": None}
    h = runs.compare_reports({"report": {"routing_score": 3.0, "routing": {"reach_rate": 0.5}}}, {"report": {"routing_score": 4.0, "routing": {"reach_rate": 0.8}}})["headline"]
    assert h["routing"]["delta"] == 1.0 and h["routing"]["rows"][0]["delta"] == 30
    assert runs.compare_reports({"report": {}}, {"report": {}})["headline"]["routing"] is None


def test_snapshot_keeps_the_expected_route():
    snap = runs._snapshot({"id": "s1", "expected_agent": "Facturation", "expected_route": ["Accueil", "Facturation"]})
    assert snap["expected_agent"] == "Facturation" and snap["expected_route"] == ["Accueil", "Facturation"]
