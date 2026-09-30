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
