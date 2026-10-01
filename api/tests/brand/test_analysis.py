"""OxeePhone configuration analysis: rules and model review."""

import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

from api.brand import analysis
from api.brand.analysis import (
    _extract_json,
    review_with_model,
    run_rules,
    transition_samples,
)

FIXTURES = Path(__file__).resolve().parents[3] / "ui/src/brand/call-detail/__fixtures__"
T0 = datetime.fromisoformat("2026-09-30T10:00:00+00:00")


def _real(name: str, definition_id: int, workflow: str) -> dict:
    raw = json.loads((FIXTURES / name).read_text())
    return {
        "id": raw["id"],
        "workflow_id": definition_id,
        "workflow_name": workflow,
        "definition_id": definition_id,
        "created_at": datetime.fromisoformat(raw["created_at"].replace("Z", "+00:00")),
        "is_completed": True,
        "mode": raw["mode"],
        "usage_info": raw["usage_info"],
        "gathered_context": raw["gathered_context"],
        "logs": raw["logs"],
    }


def _graph() -> dict:
    routing = json.loads((FIXTURES / "run10-routing.json").read_text())["graphs"][0]
    return {
        "workflow_name": "Cabinet Martin — routage",
        "workflow_json": {
            "nodes": [
                {"id": n["id"], "type": n["type"], "data": {"name": n["name"]}}
                for n in routing["nodes"]
            ],
            "edges": [
                {
                    "id": e["id"],
                    "source": e["source"],
                    "target": e["target"],
                    "data": {"label": e["label"], "condition": e["condition"]},
                }
                for e in routing["edges"]
            ],
        },
    }


def _at(s: float) -> str:
    return (T0 + timedelta(seconds=s)).isoformat()


def _synthetic(run_id: int, events: list[dict], status: str = "user_hangup") -> dict:
    return {
        "id": run_id,
        "workflow_id": 4,
        "workflow_name": "Cabinet Martin — routage",
        "definition_id": 4,
        "created_at": T0,
        "is_completed": True,
        "mode": "webrtc",
        "usage_info": {},
        "gathered_context": {"call_status": status},
        "logs": {"realtime_feedback_events": events},
    }


def _move(s, node_id, node, prev_id, prev, tool=None):
    events = [
        {
            "type": "rtf-node-transition",
            "timestamp": _at(s),
            "node_name": node,
            "payload": {
                "node_id": node_id,
                "node_name": node,
                "previous_node_id": prev_id,
                "previous_node_name": prev,
            },
        }
    ]
    if tool:
        events.append(
            {
                "type": "rtf-function-call-start",
                "timestamp": _at(s + 0.01),
                "payload": {
                    "function_name": tool,
                    "tool_call_id": f"c{s}",
                    "arguments": {},
                },
            }
        )
        events.append(
            {
                "type": "rtf-function-call-end",
                "timestamp": _at(s + 0.02),
                "payload": {
                    "function_name": tool,
                    "tool_call_id": f"c{s}",
                    "result": "{'status': 'done'}",
                },
            }
        )
    return events


def _say(s, role, text, node, dur=2.0):
    return {
        "type": "rtf-user-transcription" if role == "caller" else "rtf-bot-text",
        "timestamp": _at(s + dur),
        "node_name": node,
        "payload": {
            "text": text,
            "final": True,
            "timestamp": _at(s),
            "end_timestamp": _at(s + dur),
        },
    }


def _rules(runs):
    findings, stats, calls = run_rules(runs, {4: _graph()})
    return {f["rule"]: f for f in findings}, stats, calls


def test_real_calls_raise_latency_findings_with_models():
    rules, stats, _ = _rules([_real("run10.json", 4, "Cabinet Martin — routage")])
    reply = rules["reply_latency"]
    assert reply["severity"] in ("warning", "critical")
    assert reply["calls"] == [10]
    assert (
        "stage_llm" in rules and rules["stage_llm"]["metrics"]["model"] == "Oxee-flash"
    )
    assert stats["latency_by_agent"]["Cabinet Martin — routage"]["replies"] >= 3


def test_routing_loop_and_ping_pong():
    events = (
        _move(0, "1", "Accueil", None, None)
        + _move(10, "2", "Prise de rendez-vous", "1", "Accueil", "prise_de_rendez_vous")
        + _move(20, "1", "Accueil", "2", "Prise de rendez-vous")
        + _move(30, "2", "Prise de rendez-vous", "1", "Accueil", "prise_de_rendez_vous")
        + _move(40, "1", "Accueil", "2", "Prise de rendez-vous")
        + _move(50, "2", "Prise de rendez-vous", "1", "Accueil", "prise_de_rendez_vous")
    )
    rules, _, _ = _rules([_synthetic(101, events)])
    assert rules["routing_loop"]["severity"] == "critical"
    assert rules["routing_loop"]["calls"] == [101]
    assert "⇄" in rules["ping_pong"]["title"]
    assert "unmatched_transition" in rules  # the moves back had no pathway decision


def test_hangup_right_after_transition_and_dead_air():
    events = (
        _move(0, "1", "Accueil", None, None)
        + [
            _say(1, "agent", "Bonjour", "Accueil"),
            _say(4, "caller", "J'ai mal à la poitrine", "Accueil"),
        ]
        + [
            _say(14, "agent", "Appelez le 15", "Accueil")
        ]  # 8 s of dead air before the agent answers
        + _move(17, "3", "Urgences", "1", "Accueil", "urgence")
    )
    run = _synthetic(102, events, status="user_hangup")
    rules, _, _ = _rules([run])
    assert rules["dead_air_agent"]["metrics"]["longest_s"] == pytest.approx(8.0)
    assert rules["dead_air_agent"]["severity"] == "critical"
    assert rules["hangup_after_transition"]["node"] == "Urgences"


def test_stuck_node_and_interruptions():
    events = _move(0, "1", "Accueil", None, None)
    for i in range(10):
        events.append(_say(2 + i * 6, "caller", f"question {i}", "Accueil"))
        bot = _say(5 + i * 6, "agent", f"réponse {i}", "Accueil")
        bot["payload"]["interrupted"] = i % 2 == 0
        events.append(bot)
    rules, _, _ = _rules([_synthetic(103, events)])
    assert rules["node_stuck"]["node"] == "Accueil"
    assert rules["interruptions"]["metrics"]["interrupted"] == 5


def test_tool_errors_exclude_transitions():
    events = _move(0, "1", "Accueil", None, None) + _move(
        5, "2", "Prise de rendez-vous", "1", "Accueil", "prise_de_rendez_vous"
    )
    for i in range(4):
        events.append(
            {
                "type": "rtf-function-call-start",
                "timestamp": _at(10 + i),
                "payload": {"function_name": "book", "tool_call_id": f"b{i}"},
            }
        )
        events.append(
            {
                "type": "rtf-function-call-end",
                "timestamp": _at(13 + i),
                "payload": {
                    "function_name": "book",
                    "tool_call_id": f"b{i}",
                    "result": "{'status': 'error'}"
                    if i < 2
                    else "{'status': 'success'}",
                },
            }
        )
    rules, _, calls = _rules([_synthetic(104, events)])
    assert rules["tool_errors"]["severity"] == "critical"  # 50 %
    assert rules["tool_slow"]["metrics"]["avg_ms"] == 3000
    assert {t["name"] for t in calls[0]["tools"]} == {
        "book"
    }  # transition tool excluded


def test_transition_samples_carry_condition_and_words():
    run = _real("run10.json", 4, "Cabinet Martin — routage")
    _, _, calls = run_rules([run], {4: _graph()})
    samples = transition_samples(calls, analysis._graph_index({4: _graph()}))
    first = samples[0]
    assert (first["from"], first["to"]) == ("Accueil", "Prise de rendez-vous")
    assert "rendez-vous" in first["pathway_condition"]
    assert any("rendez-vous" in line for line in first["before"])
    assert first["other_pathways"][0]["to"] == "Urgences"


def test_extract_json_from_fenced_answer():
    assert _extract_json('Voici:\n```json\n{"summary": "ok"}\n```') == {"summary": "ok"}
    with pytest.raises(ValueError):
        _extract_json("no json here")


async def test_model_review_merges_recommendations(monkeypatch):
    captured = {}
    answer = {
        "summary": "Latency dominates.",
        "rule_findings": {
            "r1": {
                "title": "Réponses lentes",
                "detail": "médiane 3,4 s",
                "recommendation": "Use a faster model.",
            }
        },
        "findings": [
            {
                "severity": "warning",
                "category": "routing",
                "title": "Premature move",
                "detail": "x",
                "recommendation": "Tighten the condition",
                "calls": [10, "bad"],
            },
            # restates a rule category: dropped, the rules own it
            {"severity": "warning", "category": "latency", "title": "Slow again"},
        ],
    }

    def handler(request):
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(answer)}}],
                "usage": {"prompt_tokens": 5},
            },
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        analysis.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(
            *a, **{**k, "transport": httpx.MockTransport(handler)}
        ),
    )
    findings = [
        {
            "id": "r1",
            "severity": "warning",
            "category": "latency",
            "title": "t",
            "detail": "d",
            "agent": "A",
            "node": None,
            "calls": [1],
            "metrics": {},
        }
    ]
    review = await review_with_model(
        {"base_url": "http://llm/v1", "api_key": "k", "model": "Oxee-pro"},
        findings,
        {},
        [],
        language="French",
    )
    assert review["summary"] == "Latency dominates."
    assert review["rule_findings"]["r1"]["recommendation"] == "Use a faster model."
    assert [f["title"] for f in review["findings"]] == ["Premature move"]
    assert review["findings"][0]["source"] == "model" and review["findings"][0][
        "calls"
    ] == [10]
    assert captured["auth"] == "Bearer k" and captured["body"]["model"] == "Oxee-pro"
    assert "Write every text in French" in captured["body"]["messages"][0]["content"]


async def test_model_review_disables_thinking_and_retries_without_it(monkeypatch):
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "chat_template_kwargs" in body:
            return httpx.Response(400, text="unknown field chat_template_kwargs")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": '{"summary": "ok"}'},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        analysis.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(
            *a, **{**k, "transport": httpx.MockTransport(handler)}
        ),
    )
    review = await review_with_model(
        {"base_url": "http://llm/v1", "model": "m"}, [], {}, []
    )
    assert review["summary"] == "ok"
    assert bodies[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "chat_template_kwargs" not in bodies[1]


async def test_model_review_explains_reasoning_exhaustion(monkeypatch):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "", "reasoning": "..."},
                        "finish_reason": "length",
                    }
                ]
            },
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        analysis.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(
            *a, **{**k, "transport": httpx.MockTransport(handler)}
        ),
    )
    with pytest.raises(RuntimeError, match="token budget reasoning"):
        await review_with_model({"base_url": "http://llm/v1", "model": "m"}, [], {}, [])


# ------------------------------------------------------------- thresholds


def test_thresholds_change_what_rules_flag():
    run = _real("run10.json", 4, "Cabinet Martin — routage")
    strict = {f["rule"] for f in run_rules([run], {4: _graph()})[0]}
    relaxed = {
        f["rule"]
        for f in run_rules(
            [run],
            {4: _graph()},
            {
                "reply_p50_warn_ms": 9000,
                "reply_p50_crit_ms": 12000,
                "llm_stage_warn_ms": 9000,
                "dead_air_secs": 20,
            },
        )[0]
    }
    assert {"reply_latency", "stage_llm"} <= strict
    assert not {"reply_latency", "stage_llm", "dead_air_agent"} & relaxed


def test_thresholds_are_clamped_and_consistent():
    from api.brand.analysis_thresholds import DEFAULTS, normalize

    values = normalize(
        {
            "dead_air_secs": 999,
            "min_sample": "4",
            "bogus": 1,
            "reply_p50_warn_ms": 5000,
            "reply_p50_crit_ms": 1000,
        }
    )
    assert values["dead_air_secs"] == 30.0  # max
    assert values["min_sample"] == 4 and isinstance(values["min_sample"], int)
    assert "bogus" not in values
    assert values["reply_p50_crit_ms"] > values["reply_p50_warn_ms"]
    assert normalize(None) == DEFAULTS


async def test_model_threshold_suggestions_are_clamped(monkeypatch):
    from api.brand import analysis_thresholds

    answer = {
        "thresholds": {
            "dead_air_secs": {
                "value": 2.5,
                "reason": "Réceptionniste : silence perçu vite",
            },
            "tool_slow_ms": {"value": 999999, "reason": "x"},
            "unknown": {"value": 1},
        }
    }
    sent = {}

    def handler(request):
        sent["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(answer)}}]}
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        analysis_thresholds.httpx,
        "AsyncClient",
        lambda *a, **k: real_client(
            *a, **{**k, "transport": httpx.MockTransport(handler)}
        ),
    )
    out = await analysis_thresholds.suggest(
        {"base_url": "http://m/v1", "model": "m"},
        [{"name": "A"}],
        {"calls": 3},
        language="French",
    )
    assert out["dead_air_secs"] == {
        "value": 2.5,
        "reason": "Réceptionniste : silence perçu vite",
    }
    assert out["tool_slow_ms"]["value"] == 30000  # clamped to max
    assert "unknown" not in out
    assert sent["body"]["chat_template_kwargs"] == {"enable_thinking": False}
    keys = {
        t["key"]
        for t in json.loads(sent["body"]["messages"][1]["content"])["thresholds"]
    }
    assert {"dead_air_secs", "reply_p50_warn_ms", "min_sample"} <= keys


def test_observed_profile_summarises_calls():
    from api.brand.analysis_thresholds import observed_profile

    _, _, calls = run_rules(
        [_real("run10.json", 4, "Cabinet Martin — routage")], {4: _graph()}
    )
    profile = observed_profile(calls)
    assert profile["calls"] == 1 and profile["replies"] >= 3
    assert profile["reply_ms"]["p50"] <= profile["reply_ms"]["p90"]
    assert profile["silence_gap_s"]["p50"] is not None
