"""OxeePhone: automatic fixes (operations, fixability) and their simulation."""

import copy
from collections import deque

import pytest

from api.brand import fixes
from api.brand import simulation as sim

GRAPH = {
    "nodes": [
        {
            "id": "1",
            "type": "startCall",
            "data": {"name": "Accueil", "prompt": "Identifie le besoin."},
        },
        {
            "id": "2",
            "type": "agentNode",
            "data": {"name": "Urgences", "prompt": "Oriente vers le 15."},
        },
        {
            "id": "3",
            "type": "agentNode",
            "data": {"name": "Rendez-vous", "prompt": "Propose un créneau."},
        },
    ],
    "edges": [
        {
            "id": "e12",
            "source": "1",
            "target": "2",
            "data": {"label": "Urgence", "condition": "urgence"},
        },
        {
            "id": "e13",
            "source": "1",
            "target": "3",
            "data": {"label": "RDV", "condition": "rendez-vous"},
        },
        {
            "id": "e31",
            "source": "3",
            "target": "1",
            "data": {"label": "Retour", "condition": "autre besoin"},
        },
    ],
}


def test_fixability():
    assert not fixes.fixability({"rule": "reply_latency"})["fixable"]
    assert not fixes.fixability({"rule": "stage_llm"})["fixable"]
    assert not fixes.fixability({"rule": None, "category": "tools"})["fixable"]
    assert fixes.fixability({"rule": "ping_pong"}) == {
        "fixable": True,
        "reason": None,
        "review": False,
    }
    assert fixes.fixability({"rule": "node_unreached"})["review"]
    assert fixes.fixability({"rule": None, "category": "routing"})["fixable"]


def test_apply_operations_on_copies():
    ops = [
        {
            "op": "set_node_field",
            "node": "rendez-vous",
            "field": "prompt",
            "value": "Propose deux créneaux.",
        },
        {
            "op": "set_edge_field",
            "from": "Rendez-vous",
            "to": "Accueil",
            "field": "condition",
            "value": "Le patient a un AUTRE besoin.",
        },
        {"op": "set_setting", "key": "speaking_plan.stop.num_words", "value": 2},
        {"op": "set_setting", "key": "max_user_idle_timeout", "value": 15},
    ]
    before = copy.deepcopy(GRAPH)
    graph, cfg, applied = fixes.apply_operations(GRAPH, {}, ops)
    assert GRAPH == before  # untouched
    assert graph["nodes"][2]["data"]["prompt"] == "Propose deux créneaux."
    assert graph["edges"][2]["data"]["condition"] == "Le patient a un AUTRE besoin."
    assert cfg["speaking_plan"]["stop"]["num_words"] == 2
    assert (
        cfg["turn_start_strategy"] == "min_words" and cfg["turn_start_min_words"] == 2
    )
    assert cfg["max_user_idle_timeout"] == 15.0
    assert [a["field"] for a in applied] == [
        "prompt",
        "condition",
        "speaking_plan.stop.num_words",
        "max_user_idle_timeout",
    ]


@pytest.mark.parametrize(
    "op,message",
    [
        (
            {"op": "set_node_field", "node": "Nope", "field": "prompt", "value": "x"},
            "unknown node",
        ),
        (
            {
                "op": "set_node_field",
                "node": "Accueil",
                "field": "tool_uuids",
                "value": [],
            },
            "cannot be changed",
        ),
        (
            {
                "op": "set_node_field",
                "node": "Accueil",
                "field": "prompt",
                "value": " ",
            },
            "non-empty",
        ),
        (
            {
                "op": "set_edge_field",
                "from": "Urgences",
                "to": "Accueil",
                "field": "condition",
                "value": "x",
            },
            "no single transition",
        ),
        (
            {"op": "set_setting", "key": "max_call_duration", "value": 10},
            "cannot be changed",
        ),
        (
            {"op": "set_setting", "key": "speaking_plan.stop.num_words", "value": 50},
            "between",
        ),
        ({"op": "add_node"}, "unknown operation"),
    ],
)
def test_invalid_operations_are_refused(op, message):
    with pytest.raises(fixes.FixError, match=message):
        fixes.apply_operations(GRAPH, {}, [op])


def test_no_operation_is_refused():
    with pytest.raises(fixes.FixError):
        fixes.apply_operations(GRAPH, {}, [])


EVENTS = [
    {"type": "rtf-bot-text", "payload": {"text": "Bonjour"}},
    {"type": "rtf-user-transcription", "payload": {"text": "Bonjour,", "final": True}},
    {
        "type": "rtf-user-transcription",
        "payload": {"text": "un rendez-vous", "final": False},
    },
    {
        "type": "rtf-user-transcription",
        "payload": {"text": "je voudrais un rendez-vous.", "final": True},
    },
    {"type": "rtf-node-transition", "payload": {"node_name": "Rendez-vous"}},
    {
        "type": "rtf-function-call-end",
        "payload": {
            "function_name": "check_availability",
            "result": {"slots": ["11h"]},
        },
    },
    {"type": "rtf-bot-text", "payload": {"text": "J'ai 11h."}},
    {"type": "rtf-user-transcription", "payload": {"text": "Parfait.", "final": True}},
]


def test_caller_script_and_recorded_data():
    assert sim.caller_script(EVENTS) == [
        "Bonjour, je voudrais un rendez-vous.",
        "Parfait.",
    ]
    assert sim.recorded_path(EVENTS) == ["Rendez-vous"]
    assert sim.recorded_tool_results(EVENTS) == {
        "check_availability": deque([{"slots": ["11h"]}])
    }


def test_tool_override_only_inside_a_simulation():
    assert sim.tool_override("check_availability", {}) is None
    state = {
        "recorded": {"check_availability": deque([{"slots": ["11h"]}])},
        "calls": [],
    }
    token = sim._tool_results.set(state)
    try:
        assert sim.tool_override("check_availability", {"day": "mardi"}) == {
            "slots": ["11h"]
        }
        assert sim.tool_override("check_availability", {}) == {
            "slots": ["11h"]
        }  # repeats
        assert sim.tool_override("book", {})["status"] == "simulated"
        assert [c["name"] for c in state["calls"]] == [
            "check_availability",
            "check_availability",
            "book",
        ]
    finally:
        sim._tool_results.reset(token)
    assert sim.tool_override("book", {}) is None


def test_path_metrics():
    path = ["Accueil", "Rendez-vous", "Accueil", "Rendez-vous"]
    transcript = [
        {"role": "agent", "text": "a", "node": "Accueil"},
        {"role": "agent", "text": "b", "node": "Rendez-vous"},
        {"role": "agent", "text": "c", "node": "Rendez-vous"},
    ]
    m = sim.path_metrics(path, transcript)
    assert m == {
        "steps": 4,
        "revisits": 2,
        "ping_pong": 2,
        "max_replies_in_a_node": 2,
        "agent_replies": 3,
    }


@pytest.mark.asyncio
async def test_chat_json_retries_gateway_errors(monkeypatch):
    import httpx

    from api.brand import llm

    answers = [
        httpx.Response(503, text="busy"),
        httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}
                ]
            },
        ),
    ]
    calls = []

    async def post(self, url, headers=None, json=None):
        calls.append(url)
        return answers[len(calls) - 1]

    async def no_sleep(_):
        return None

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    monkeypatch.setattr(llm.asyncio, "sleep", no_sleep)
    result = await llm.chat_json(
        {"base_url": "http://m/v1", "model": "x"}, "sys", {"a": 1}
    )
    assert result == {"ok": True} and len(calls) == 2


@pytest.mark.parametrize(
    "model,cases,expected",
    [
        ("pass", [{"verdict": "improved", "candidate": {}}], "pass"),
        ("unchanged", [{"verdict": "unchanged", "candidate": {}}] * 3, "inconclusive"),
        (
            None,
            [
                {"verdict": "improved", "candidate": {}},
                {"verdict": "unchanged", "candidate": {}},
            ],
            "mixed",
        ),
        (
            None,
            [
                {"verdict": "improved", "candidate": {}},
                {"verdict": "regressed", "candidate": {}},
            ],
            "fail",
        ),
        ("pass", [{"verdict": "improved", "candidate": {"error": "boom"}}], "fail"),
        (None, [{"candidate": {}}], None),
    ],
)
def test_overall_verdict(model, cases, expected):
    assert fixes.overall_verdict(model, cases) == expected


@pytest.fixture
def fix_store(monkeypatch):
    data = {}

    async def get(org, fix_id):
        return copy.deepcopy(data.get(fix_id))

    async def save(org, fix):
        data[fix["id"]] = copy.deepcopy(fix)
        return fix

    monkeypatch.setattr(fixes, "get", get)
    monkeypatch.setattr(fixes, "save", save)
    return data


def _published_fix(**extra):
    return {
        "id": "f1",
        "status": "published",
        "workflow_id": 2,
        "base_definition_id": 10,
        "draft_definition_id": 11,
        "finding": {
            "id": "r6",
            "rule": "dead_air_caller",
            "node": None,
            "title": "Silences",
        },
        **extra,
    }


def _patch_follow_up(monkeypatch, after_runs, before_runs, found_after, found_before):
    from api.brand import analysis, analysis_thresholds

    async def recent_calls(workflow_id, *, organization_id, limit, definition_id):
        return after_runs if definition_id == 11 else before_runs

    async def graphs(ids, *, organization_id):
        return {}

    async def load(org):
        return {"values": {}}

    def run_rules(runs, graphs, th):
        return (found_after if runs is after_runs else found_before), {}, []

    monkeypatch.setattr(fixes.brand_db, "recent_calls", recent_calls)
    monkeypatch.setattr(fixes.brand_db, "get_definition_graphs", graphs)
    monkeypatch.setattr(analysis_thresholds, "load", load)
    monkeypatch.setattr(analysis, "run_rules", run_rules)


RUNS = [{"id": i, "definition_id": 11} for i in range(3)]
OLD = [{"id": 10 + i, "definition_id": 10} for i in range(3)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "after,before,found_after,found_before,status",
    [
        (RUNS[:2], OLD, [], [], "waiting"),
        (RUNS, OLD, [], [{"rule": "dead_air_caller", "severity": "info"}], "fixed"),
        (
            RUNS,
            OLD,
            [{"rule": "dead_air_caller", "severity": "info"}],
            [{"rule": "dead_air_caller", "severity": "info"}],
            "still_present",
        ),
        (
            RUNS,
            OLD,
            [{"rule": "dead_air_caller", "severity": "warning"}],
            [{"rule": "dead_air_caller", "severity": "info"}],
            "worse",
        ),
        (RUNS, OLD, [{"rule": "ping_pong", "severity": "warning"}], [], "fixed"),
    ],
)
async def test_follow_up(
    fix_store, monkeypatch, after, before, found_after, found_before, status
):
    fix_store["f1"] = _published_fix()
    _patch_follow_up(monkeypatch, after, before, found_after, found_before)
    result = await fixes.follow_up(1, "f1")
    assert result["status"] == status
    assert fix_store["f1"]["follow_up"]["status"] == status


@pytest.mark.asyncio
async def test_follow_up_of_a_model_finding_is_manual(fix_store, monkeypatch):
    fix_store["f1"] = _published_fix(
        finding={"id": "m1", "rule": None, "node": None, "title": "x"}
    )
    _patch_follow_up(monkeypatch, RUNS, OLD, [], [])
    assert (await fixes.follow_up(1, "f1"))["status"] == "manual"


@pytest.mark.asyncio
async def test_rollback(fix_store, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    fix_store["f1"] = _published_fix()
    fix_store["f2"] = _published_fix(id="f2")
    workflow = SimpleNamespace(released_definition_id=11)
    monkeypatch.setattr(
        fixes.db_client, "get_workflow", AsyncMock(return_value=workflow)
    )
    restore = AsyncMock(return_value=SimpleNamespace(version_number=3))
    monkeypatch.setattr(fixes.versions, "restore", restore)
    monkeypatch.setattr(
        fixes.db_client,
        "publish_workflow_draft",
        AsyncMock(return_value=SimpleNamespace(id=12)),
    )
    monkeypatch.setattr(fixes.versions, "record_published", AsyncMock())
    monkeypatch.setattr(
        fixes.versions, "get_meta", AsyncMock(return_value={"fixes": ["f1", "f2"]})
    )
    user = SimpleNamespace(id=1, email="a@x")

    result = await fixes.rollback(1, "f1", user)
    assert restore.await_args.args[:2] == (2, 10)
    assert result["status"] == "rolled_back" and result["rolled_back_to"] == 3
    assert fix_store["f2"]["status"] == "rolled_back"  # same version, same fate

    fix_store["f3"] = _published_fix(id="f3")
    workflow.released_definition_id = 99  # published again since
    monkeypatch.setattr(
        fixes.brand_db,
        "get_workflow_version",
        AsyncMock(return_value=SimpleNamespace(version_number=5)),
    )
    with pytest.raises(fixes.FixError, match="published again"):
        await fixes.rollback(1, "f3", user)


@pytest.mark.asyncio
async def test_no_new_proposal_while_a_fix_of_the_same_problem_awaits_calls(
    fix_store, monkeypatch
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from api.brand import analysis

    fix_store["prior"] = _published_fix(
        id="prior", draft_version_number=2, updated_at="2026-10-01T00:00"
    )
    fix_store["new"] = {
        "id": "new",
        "status": "proposing",
        "workflow_id": 2,
        "language": "French",
        "finding": {
            "id": "r6",
            "rule": "dead_air_caller",
            "node": None,
            "title": "Silences",
            "calls": [8, 9],
        },
    }
    published = SimpleNamespace(
        id=11, version_number=2, workflow_json={}, workflow_configurations={}
    )
    monkeypatch.setattr(
        fixes,
        "_published",
        AsyncMock(return_value=(SimpleNamespace(name="Accueil"), published)),
    )
    monkeypatch.setattr(
        analysis,
        "resolve_analysis_model",
        AsyncMock(return_value={"model": "m", "base_url": "http://m"}),
    )
    monkeypatch.setattr(
        fixes.brand_db,
        "get_runs_by_ids",
        AsyncMock(
            return_value=[
                {"id": 8, "definition_id": 10},
                {"id": 9, "definition_id": 10},
            ]
        ),
    )

    async def list_fixes(org, *, report_id=None, workflow_id=None):
        return list(fix_store.values())

    monkeypatch.setattr(fixes, "list_fixes", list_fixes)
    await fixes.propose(1, "new")
    assert fix_store["new"]["status"] == "not_fixable"
    assert "Already fixed in v2" in fix_store["new"]["reason"]
