"""OxeePhone: test campaigns (settings, scenarios, tester hooks, judge, report)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from api.brand import test_calls as calls
from api.brand import test_campaigns as campaigns
from api.brand import test_runs as runs


def test_ranges_are_clamped_and_ordered():
    ranges = campaigns.normalize_ranges({"mood": [5, 2], "traps": [0, 9]})
    assert ranges["mood"] == [2, 5]
    assert ranges["traps"] == [1, 5]
    assert ranges["vocabulary"] == campaigns.DEFAULT_RANGES["vocabulary"]
    with pytest.raises(campaigns.CampaignError):
        campaigns.normalize_ranges({"mood": "x"})
    assert campaigns.normalize_speed([2.5, 0.1]) == [0.7, 1.6]


def test_levels_cover_every_value_of_each_range():
    ranges = campaigns.normalize_ranges({"mood": [2, 4], "traps": [3, 3]})
    levels = campaigns.draw_levels(ranges, 9, seed=7)
    assert len(levels) == 9
    moods = [lv["mood"] for lv in levels]
    assert sorted(set(moods)) == [2, 3, 4]
    assert all(moods.count(v) == 3 for v in (2, 3, 4))
    assert {lv["traps"] for lv in levels} == {3}
    # Same seed, same campaign.
    assert campaigns.draw_levels(ranges, 9, seed=7) == levels


def test_speeds_spread_over_the_range():
    speeds = campaigns.draw_speeds([0.9, 1.3], 5, seed=1)
    assert sorted(speeds) == [0.9, 1.0, 1.1, 1.2, 1.3]
    assert campaigns.draw_speeds([1.0, 1.0], 3, seed=1) == [1.0, 1.0, 1.0]


def test_pools_avoid_repeats():
    scenarios = [{} for _ in range(5)]
    settings = {
        "voices": [{"id": f"v{i}", "gender": "female"} for i in range(5)],
        "caller_numbers": ["+33600000001", "+33600000002"],
    }
    campaigns._assign_pools(scenarios, settings, seed=3)
    assert len({s["voice"]["id"] for s in scenarios}) == 5
    numbers = [s["caller_number"] for s in scenarios]
    assert set(numbers) == {"+33600000001", "+33600000002"}


def test_clean_voices_and_numbers():
    voices = campaigns._clean_voices(
        ["fr_cedric", {"id": "fr_cedric"}, {"id": "fr_lea", "gender": "Female"}, {}]
    )
    assert [v["id"] for v in voices] == ["fr_cedric", "fr_lea"]
    assert voices[0]["gender"] == "unknown" and voices[1]["gender"] == "female"
    assert campaigns._clean_numbers([" 0601 ", "0601", "", None, "0602"]) == [
        "0601",
        "0602",
    ]


def test_tester_prompt_describes_the_levels():
    prompt = campaigns.tester_prompt(
        {
            "persona": {"name": "Marie", "age": 41},
            "goal": "Prendre rendez-vous",
            "levels": {"mood": 5, "depth": 4, "impatience": 3},
            "facts": {"date de naissance": "12/03/1985"},
        },
        agent_name="Cabinet Martin",
        language="French",
    )
    assert "Cabinet Martin" in prompt and "Speak French" in prompt
    assert campaigns.DIMENSIONS["mood"]["levels"][5] in prompt
    assert campaigns.DIMENSIONS["impatience"]["levels"][3] in prompt
    # Depth drives the generation, not the caller's behaviour.
    assert campaigns.DIMENSIONS["depth"]["levels"][4] not in prompt
    assert "12/03/1985" in prompt


def test_tester_graph_is_valid():
    from api.services.workflow.dto import ReactFlowDTO

    ReactFlowDTO.model_validate(campaigns.tester_graph())


def test_scenario_edition_and_variants():
    campaign = {
        "scenarios": [
            {
                "id": "s1",
                "title": "RDV",
                "levels": {"mood": 1},
                "speed": 1.0,
                "variant_of": None,
            }
        ]
    }
    campaigns.update_scenario(
        campaign,
        "s1",
        {"levels": {"mood": 9, "nope": 2}, "speed": 3, "criteria": ["a", " "]},
    )
    s = campaign["scenarios"][0]
    assert s["levels"] == {"mood": 5} and s["speed"] == 1.6 and s["criteria"] == ["a"]
    variant = campaigns.duplicate_scenario(campaign, "s1", {"mood": 2})
    assert variant["variant_of"] == "s1" and variant["levels"] == {"mood": 2}
    assert [x["id"] for x in campaign["scenarios"]] == ["s1", variant["id"]]
    with pytest.raises(LookupError):
        campaigns.update_scenario(campaign, "nope", {})


# --- Tester and agent hooks --------------------------------------------------------


def test_tester_configs_only_change_the_tester():
    base = {"model_overrides": {"llm": {"model": "m"}}, "max_call_duration": 600}
    assert calls.tester_configs(base, {"caller_number": "1"}) is base
    tester = calls.tester_configs(
        base,
        {
            "oxee_tester": {
                "voice": "fr_lea",
                "speed": 1.2,
                "impatience": 5,
                "max_duration": 240,
            }
        },
    )
    assert tester["voice_override"] == {"voice": "fr_lea", "speed": 1.2}
    assert tester["model_overrides"] == {"llm": {"model": "m"}}
    assert tester["speaking_plan"]["start"]["on_punctuation_seconds"] == 0.05
    assert tester["max_call_duration"] == 240
    assert base == {
        "model_overrides": {"llm": {"model": "m"}},
        "max_call_duration": 600,
    }
    assert calls.listens_first({"oxee_tester": {}}) and not calls.listens_first({})


def test_impatience_makes_the_tester_answer_sooner():
    waits = [
        calls.impatience_plan(i)["start"]["on_punctuation_seconds"] for i in range(1, 6)
    ]
    assert waits == sorted(waits, reverse=True)


def test_caller_id_carries_the_token():
    token = calls.new_token()
    cid = calls.caller_id(token, "+33612345678")
    assert cid == f'"OXT{token}" <+33612345678>'
    assert calls.TOKEN.search(cid).group(1) == token


@pytest.fixture
def config_store(monkeypatch):
    from api.db import db_client

    data = {}

    async def get_configuration(org, key):
        value = data.get((org, key))
        return SimpleNamespace(value=value) if value is not None else None

    async def upsert_configuration(org, key, value):
        data[(org, key)] = value

    monkeypatch.setattr(db_client, "get_configuration", get_configuration)
    monkeypatch.setattr(db_client, "upsert_configuration", upsert_configuration)
    return data


@pytest.mark.asyncio
async def test_claim_inbound_once(config_store):
    token = "a1b2c3d4e5f6"
    await calls.register_call(
        7,
        token,
        {
            "workflow_id": 3,
            "definition_id": 42,
            "agent_run_name": "OXEE-TEST-x-1-agent",
            "test": {"tools_mode": "simulated"},
        },
    )
    assert await calls.claim_inbound(7, "Jean Dupont", "0601") is None
    assert await calls.claim_inbound(8, f"OXT{token}") is None  # other org
    claimed = await calls.claim_inbound(7, f"OXT{token}", "0601", "7001")
    assert claimed == {
        "workflow_id": 3,
        "definition_id": 42,
        "run_name": "OXEE-TEST-x-1-agent",
        "context": {"oxee_test": {"tools_mode": "simulated"}},
    }
    assert await calls.claim_inbound(7, f"OXT{token}") is None  # single use


@pytest.mark.asyncio
async def test_claim_inbound_expires(config_store):
    token = "0123456789ab"
    config_store[(7, calls.CALL_PREFIX + token)] = {
        "workflow_id": 3,
        "definition_id": 42,
        "agent_run_name": "n",
        "test": {},
        "created_at": (datetime.now(UTC) - timedelta(minutes=30)).isoformat(),
    }
    assert await calls.claim_inbound(7, f"OXT{token}") is None


def test_post_call_effects_follow_the_tools_mode():
    assert calls.skip_test_call_effects({"oxee_test": {"tools_mode": "simulated"}})
    assert not calls.skip_test_call_effects({"oxee_test": {"tools_mode": "real"}})
    assert not calls.skip_test_call_effects({"caller_number": "1"})


@pytest.mark.asyncio
async def test_tool_override_modes(monkeypatch):
    engine = SimpleNamespace(_call_context_vars={}, _gathered_context={})
    assert await calls.tool_override(engine, "book", {}) is None  # production call

    async def simulate(org, test, name, args, tool):
        return {"simulated": name}

    monkeypatch.setattr(calls, "_simulate_tool", simulate)
    engine._call_context_vars = {"oxee_test": {"tools_mode": "simulated"}}
    assert await calls.tool_override(engine, "book", {}) == {"simulated": "book"}
    engine._call_context_vars = {"oxee_test": {"tools_mode": "real"}}
    assert await calls.tool_override(engine, "book", {}) is None

    seen = {}

    async def execute_http_tool(**kwargs):
        seen.update(kwargs)
        return {"ok": True}

    import api.services.workflow.tools.custom_tool as custom_tool

    monkeypatch.setattr(custom_tool, "execute_http_tool", execute_http_tool)
    from api.db.models import ToolModel

    tool = ToolModel(name="book", definition={"config": {"headers": {"A": "1"}}})
    engine._call_context_vars = {"oxee_test": {"tools_mode": "real_with_header"}}
    assert await calls.tool_override(engine, "book", {}, tool=tool) == {"ok": True}
    assert seen["tool"].definition["config"]["headers"] == {
        "A": "1",
        "X-Oxee-Test": "1",
    }
    assert tool.definition["config"]["headers"] == {"A": "1"}  # untouched


# --- Judge, report, comparison ---------------------------------------------------------


METRICS = {
    "end_node": "Confirmation",
    "tools": [{"name": "check_availability", "ms": 300, "failed": False}],
    "extracted_variables": {"Date_RDV": "mardi 14h", "phone": "06 12 34 56 78"},
}


def test_deterministic_checks():
    checks = runs.deterministic_checks(
        {
            "expected_end_node": "confirmation",
            "expected_tools": ["check availability", "send_sms"],
            "expected_variables": {
                "date_rdv": "Mardi 14h",
                "phone": "0612345678",
                "name": "Léa",
            },
        },
        METRICS,
    )
    assert [c["pass"] for c in checks] == [True, True, False, True, True, False]


@pytest.mark.parametrize(
    "judge,checks,expected",
    [
        ({"goal_reached": True, "criteria": [{"pass": True}] * 3}, [], "pass"),
        (
            {"goal_reached": True, "criteria": [{"pass": True}] * 3},
            [{"pass": False}],
            "partial",
        ),
        (
            {
                "goal_reached": True,
                "criteria": [{"pass": True}],
                "forbidden": [{"violated": True}],
            },
            [],
            "fail",
        ),
        ({"goal_reached": False, "criteria": [{"pass": True}] * 3}, [], "partial"),
        ({"goal_reached": False, "criteria": [{"pass": False}] * 3}, [], "fail"),
        (None, [], "fail"),
    ],
)
def test_final_verdict(judge, checks, expected):
    criteria = len((judge or {}).get("criteria") or [])
    assert runs.final_verdict(judge, checks, criteria) == expected


def _call(index, scenario_id, verdict, mood, path_ids, latency, interruptions=0):
    return {
        "index": index,
        "scenario_id": scenario_id,
        "scenario": {"title": scenario_id, "levels": {"mood": mood}, "speed": 1.0},
        "status": "done",
        "verdict": verdict,
        "judge": {
            "goal_reached": verdict == "pass",
            "criteria": [{"text": "Asks the date", "pass": verdict == "pass"}],
            "scores": {"accuracy": 4 if verdict == "pass" else 2},
            "failure_node": None if verdict == "pass" else "Accueil",
        },
        "checks": [],
        "metrics": {
            "duration_seconds": 60.0,
            "caller_turns": 4,
            "agent_turns": 5,
            "interruptions": interruptions,
            "latency": {
                "turns": len(latency),
                "p50_ms": None,
                "p90_ms": None,
                "greeting_ms": 800,
                "stages": {"llm": 500.0},
                "values_ms": latency,
            },
            "tools": [{"name": "check", "ms": 200, "failed": verdict == "fail"}],
            "path": [],
            "path_ids": path_ids,
            "edges": ["e13"] if "3" in path_ids else [],
            "end_node": None,
            "end_status": "user_hangup",
            "extracted_variables": {},
            "errors": 0,
        },
    }


INDEX = {
    "names": {"1": "Accueil", "2": "Urgences", "3": "Rendez-vous"},
    "edges": [
        {"id": "e12", "source": "1", "target": "2", "label": "Urgence"},
        {"id": "e13", "source": "1", "target": "3", "label": "RDV"},
    ],
}


def _execution(calls_):
    return {"id": "x", "calls": calls_}


def test_aggregate():
    execution = _execution(
        [
            _call(1, "s1", "pass", 1, ["1", "3"], [900, 1100], interruptions=1),
            _call(2, "s1", "fail", 1, ["1"], [2500]),
            _call(3, "s2", "pass", 4, ["1", "3"], [1000]),
            {**_call(4, "s3", None, 2, [], []), "status": "error", "metrics": None},
        ]
    )
    report = runs.aggregate(execution, INDEX)
    assert report["verdicts"] == {"pass": 2, "partial": 0, "fail": 1}
    assert report["pass_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert report["errors"] == 1
    s1 = next(s for s in report["by_scenario"] if s["scenario_id"] == "s1")
    assert s1["unstable"] and s1["pass_rate"] == 0.5
    assert report["by_dimension"]["mood"]["1"]["pass_rate"] == 0.5
    assert report["by_dimension"]["mood"]["4"]["pass_rate"] == 1.0
    assert report["coverage"]["nodes_visited"] == 2
    assert report["coverage"]["nodes_never_visited"] == ["Urgences"]
    assert report["coverage"]["edges_used"] == 1
    assert report["latency"]["p50_ms"] == 1050.0
    assert report["latency"]["slow_turns_rate"] == 0.25
    assert report["interruptions"]["total"] == 1
    assert report["criteria_failures"] == [{"text": "Asks the date", "count": 1}]
    assert report["failure_nodes"] == {"Accueil": 1}
    assert report["tools"]["failure_rate"] == pytest.approx(1 / 3, abs=1e-3)


def test_compare_reports():
    a = {
        "report": runs.aggregate(
            _execution(
                [
                    _call(1, "s1", "fail", 1, ["1"], [2000]),
                    _call(2, "s2", "pass", 1, ["1"], [900]),
                ]
            ),
            INDEX,
        )
    }
    b = {
        "report": runs.aggregate(
            _execution(
                [
                    _call(1, "s1", "pass", 1, ["1", "3"], [1000]),
                    _call(2, "s2", "pass", 1, ["1"], [900]),
                ]
            ),
            INDEX,
        )
    }
    result = runs.compare_reports(a, b)
    pass_rate = next(i for i in result["indicators"] if i["key"] == "pass_rate")
    assert pass_rate["delta"] == 0.5 and pass_rate["trend"] == "better"
    latency = next(i for i in result["indicators"] if i["key"] == "latency.p50_ms")
    assert latency["trend"] == "better"
    assert result["scenarios"][0] == {
        "scenario_id": "s1",
        "title": "s1",
        "a": {"calls": 1, "pass": 0, "partial": 0, "fail": 1, "error": 0, "score": 0.0},
        "b": {"calls": 1, "pass": 1, "partial": 0, "fail": 0, "error": 0, "score": 1.0},
        "change": "improved",
    }
    assert result["changes"] == {"improved": 1, "same": 1}
    assert result["coverage"]["nodes_gained"] == ["Rendez-vous"]


def test_finding_from_a_failed_call():
    call = _call(2, "s1", "fail", 1, ["1"], [2500])
    call.update(agent_run_id=99, checks=[{"label": "Calls book", "pass": False}])
    finding = runs.finding_from_call({"id": "x", "workflow_name": "Cabinet"}, call)
    assert finding["calls"] == [99] and finding["node"] == "Accueil"
    assert "Asks the date" in finding["detail"] and "Calls book" in finding["detail"]
    from api.brand import fixes

    assert fixes.fixability(finding)["fixable"]


def test_text_end_tag():
    assert runs._strip_end("Merci, au revoir. <END_CALL>") == (
        "Merci, au revoir.",
        True,
    )
    assert runs._strip_end("Bonjour") == ("Bonjour", False)


def test_tester_and_test_runs_are_not_production():
    from sqlalchemy.dialects import postgresql

    from api.brand.db import production_runs

    sql = str(production_runs().compile(dialect=postgresql.dialect()))
    assert sql.count("workflow_runs.name NOT LIKE") == 2


# --- A whole text execution, with fakes for the DB, the agent and the models ----------


@pytest.mark.asyncio
async def test_text_execution_end_to_end(monkeypatch):
    from api.brand import analysis
    from api.brand import llm as brand_llm
    from api.db import db_client
    from api.services.workflow import text_chat_runner

    store: dict = {}

    async def save(org, execution):
        store[execution["id"]] = execution
        return execution

    async def get(org, execution_id):
        return store.get(execution_id)

    monkeypatch.setattr(runs, "save", save)
    monkeypatch.setattr(runs, "get", get)

    async def model(org):
        return {"base_url": "http://m/v1", "model": "judge"}

    monkeypatch.setattr(analysis, "resolve_analysis_model", model)
    from api.brand import analysis_thresholds

    async def thresholds(org):
        return {"values": dict(analysis_thresholds.DEFAULTS)}

    monkeypatch.setattr(analysis_thresholds, "load", thresholds)

    graph = {
        "nodes": [
            {
                "id": "1",
                "type": "startCall",
                "data": {"name": "Accueil", "prompt": "Accueille."},
            },
            {
                "id": "2",
                "type": "endCall",
                "data": {"name": "Fin", "prompt": "Au revoir."},
            },
        ],
        "edges": [
            {
                "id": "e",
                "source": "1",
                "target": "2",
                "data": {"label": "fin", "condition": "fini"},
            }
        ],
    }

    async def graphs(ids, organization_id):
        return {
            42: {"workflow_id": 3, "workflow_name": "Cabinet", "workflow_json": graph}
        }

    async def version(workflow_id, definition_id):
        return SimpleNamespace(id=42, workflow_json=graph, workflow_configurations={})

    monkeypatch.setattr(runs.brand_db, "get_definition_graphs", graphs)
    monkeypatch.setattr(runs.brand_db, "get_workflow_version", version)

    runs_db: dict = {}

    async def create_workflow_run(**kwargs):
        run = SimpleNamespace(id=100 + len(runs_db), **kwargs)
        runs_db[run.id] = {
            "id": run.id,
            "workflow_id": 3,
            "definition_id": 42,
            "name": kwargs["name"],
            "initial_context": kwargs["initial_context"],
            "usage_info": {},
            "gathered_context": {},
            "logs": {},
        }
        return run

    async def update_workflow_run(run_id, **kwargs):
        r = runs_db[run_id]
        for key in ("gathered_context", "logs", "usage_info"):
            if kwargs.get(key):
                r[key] = {**r[key], **kwargs[key]}

    async def get_runs_by_ids(ids, organization_id):
        return [runs_db[i] for i in ids if i in runs_db]

    monkeypatch.setattr(db_client, "create_workflow_run", create_workflow_run)
    monkeypatch.setattr(db_client, "update_workflow_run", update_workflow_run)
    monkeypatch.setattr(runs.brand_db, "get_runs_by_ids", get_runs_by_ids)

    turns = {"n": 0}

    async def execute_turn(*, workflow_run_id, workflow_id, session_data, checkpoint):
        turns["n"] += 1
        user = session_data["turns"][-1].get("user_message") or {}
        done = turns["n"] >= 3
        events = [
            {
                "type": "node_transition",
                "payload": {
                    "node_id": "1" if not done else "2",
                    "node_name": "Accueil" if not done else "Fin",
                },
            }
        ]
        return text_chat_runner.TextChatTurnExecutionResult(
            assistant_text=(
                "Bonjour, cabinet Martin."
                if turns["n"] == 1
                else f"Bien noté ({user.get('text')})."
            ),
            assistant_created_at="2026-10-02T10:00:00+00:00",
            events=events,
            usage={},
            checkpoint=checkpoint,
            gathered_context={"extracted_variables": {"motif": "rendez-vous"}},
            initial_context={},
            state="running",
            is_completed=done,
        )

    monkeypatch.setattr(
        text_chat_runner, "execute_text_chat_pending_turn", execute_turn
    )

    async def tester(model_, messages, **kwargs):
        return (
            "Je voudrais un rendez-vous."
            if len(messages) < 4
            else "Merci, au revoir. <END_CALL>"
        )

    async def judge(model_, system, payload, **kwargs):
        assert payload["transcript"], "the judge gets the transcript"
        return {
            "goal_reached": True,
            "criteria": [{"index": 1, "pass": True, "evidence": "ok"}],
            "forbidden": [],
            "scores": {"accuracy": 5, "tone": 4},
            "summary": "OK",
            "issues": [],
        }

    monkeypatch.setattr(brand_llm, "chat_messages", tester)
    monkeypatch.setattr(brand_llm, "chat_json", judge)

    scenario = {
        "id": "s1",
        "title": "Prise de RDV",
        "levels": {"mood": 2},
        "speed": 1.0,
        "persona": {"name": "Marie"},
        "goal": "RDV",
        "criteria": ["Demande le motif"],
        "forbidden": [],
        "expected_variables": {"motif": "rendez-vous"},
        "expected_end_node": "Fin",
        "facts": {},
        "enabled": True,
    }
    execution = {
        "id": "ex1",
        "workflow_id": 3,
        "workflow_name": "Cabinet",
        "definition_id": 42,
        "use_draft": True,
        "channel": "text",
        "passes": 1,
        "concurrency": 2,
        "tools_mode": "simulated",
        "language": "French",
        "max_duration_seconds": 300,
        "status": "queued",
        "calls": [
            {
                "index": 1,
                "pass": 1,
                "scenario_id": "s1",
                "scenario": scenario,
                "status": "pending",
            }
        ],
    }
    store["ex1"] = execution
    await runs.run(7, "ex1", user_id=1)

    done = store["ex1"]
    call = done["calls"][0]
    assert done["status"] == "done", done.get("error")
    assert call["status"] == "done", call.get("error")
    assert call["ended_by"] == "agent"
    assert call["verdict"] == "pass"
    assert [c["pass"] for c in call["checks"]] == [True, True]
    run = runs_db[call["agent_run_id"]]
    assert run["name"] == "OXEE-TEST-ex1-1-agent"
    assert run["initial_context"]["oxee_test"]["tools_mode"] == "simulated"
    assert done["report"]["pass_rate"] == 1.0
    assert done["report"]["coverage"]["nodes_visited"] == 2
    tech = done["report"]["technical"]
    assert [p["key"] for p in tech["posts"]] == ["reliability"]  # text: no timing
    assert tech["score"] == 5 and call["technical"]["score"] == 5


# --- Technical quality -----------------------------------------------------------------


def _phone_call(index, totals, llm, status="done", errors=0, interruptions=0, greeting=900):
    return {
        "index": index,
        "scenario": {"title": f"s{index}"},
        "status": status,
        "metrics": {
            "latency": {
                "greeting_ms": greeting,
                "turn_stages": [
                    {"total": t, "perceived": t + 300, "stages": {"endpointing": 300, "transcriber": 200, "llm": l, "voice": 250, "sentence": 100}}
                    for t, l in zip(totals, llm)
                ],
            },
            "tools": [{"name": "check", "ms": 400, "failed": False}],
            "agent_turns": 4,
            "interruptions": interruptions,
            "errors": errors,
            "models": {"llm_model": "Oxee-flash", "stt_model": "voxee-stt"},
        },
    }


def test_grade_steps():
    from api.brand.test_technical import grade

    assert [grade(v, 1000) for v in (400, 700, 1000, 1400, 1600)] == [5, 4, 3, 2, 1]
    assert grade(2500, 2000, 3000) == 2 and grade(None, 1000) is None


def test_technical_report_grades_each_post():
    from api.brand.analysis_thresholds import DEFAULTS
    from api.brand.test_technical import call_technical, technical_report

    calls = [
        _phone_call(1, [1200, 1300], [500, 600]),
        _phone_call(2, [1500, 1400], [2400, 2600], interruptions=2),
        _phone_call(3, [], [], status="error"),
    ]
    for c in calls:
        if c["metrics"]["latency"]["turn_stages"]:
            c["technical"] = call_technical(c, DEFAULTS, channel="phone")
    report = technical_report(calls, DEFAULTS, channel="phone")
    posts = {p["key"]: p for p in report["posts"]}
    assert posts["reply"]["p50"] == 1350 and posts["reply"]["score"] == 4
    assert posts["llm"]["model"] == "Oxee-flash"
    assert posts["llm"]["score"] == 2  # p50 1550 > 1500, under 1.5 x
    assert posts["transcriber"]["score"] == 5 and posts["transcriber"]["share"]
    assert posts["reliability"]["p50"] == pytest.approx(1 / 3, abs=1e-3)
    assert posts["reliability"]["score"] == 1
    assert posts["turn_taking"]["p50"] == pytest.approx(2 / 12, abs=1e-3)
    assert 1 <= report["score"] <= 5
    assert report["worst_calls"][0]["index"] == 2
    assert report["worst_calls"][0]["weakest"] == "LLM"
    text = technical_report(calls, DEFAULTS, channel="text")
    assert {p["key"] for p in text["posts"]} == {"tools", "reliability"}
    # The end-of-turn wait is a setting: shown, not scored, not in the reply.
    assert "endpointing" not in posts
    wait = next(i for i in report["info_stages"] if i["key"] == "endpointing")
    assert wait["counted"] is False and wait["p50"] == 300
    assert report["perceived_p50"] == 1650


def test_latency_of_older_calls_is_upgraded():
    from api.brand.test_technical import upgrade_latency

    metrics = {"latency": {"turn_stages": [{"total": 1500, "stages": {"endpointing": 400}}]}}
    upgrade_latency(metrics)
    turn = metrics["latency"]["turn_stages"][0]
    assert (turn["total"], turn["perceived"]) == (1100, 1500)
    assert metrics["latency"]["p50_ms"] == 1100 and metrics["latency"]["perceived_p50_ms"] == 1500
    upgrade_latency(metrics)  # idempotent
    assert metrics["latency"]["turn_stages"][0]["total"] == 1100


def test_compare_headline_scores():
    a = {"report": {"quality_score": 3.5, "scores": {"accuracy": 3.0, "tone": 4.0}, "technical": {"score": 4.2, "posts": [{"key": "llm", "label": "LLM", "unit": "ms", "score": 4, "p50": 900}]}}}
    b = {"report": {"quality_score": 4.0, "scores": {"accuracy": 4.0, "tone": 4.0}, "technical": {"score": 3.6, "posts": [{"key": "llm", "label": "LLM", "unit": "ms", "score": 2, "p50": 1700}]}}}
    h = runs.compare_reports(a, b)["headline"]
    assert h["quality"]["delta"] == 0.5 and h["technical"]["delta"] == -0.6
    accuracy = next(r for r in h["quality"]["rows"] if r["key"] == "accuracy")
    assert accuracy["delta"] == 1.0
    assert h["technical"]["rows"] == [
        {"key": "llm", "label": "LLM", "unit": "ms", "a": 4, "b": 2, "a_value": 900, "b_value": 1700, "delta": -2}
    ]


@pytest.mark.asyncio
async def test_tester_opens_when_it_heard_nothing(monkeypatch):
    import asyncio

    monkeypatch.setattr(calls, "TESTER_OPENING_SECS", 0.01)
    opened = []

    class _Context:
        def __init__(self, messages):
            self._m = messages

        def get_messages(self):
            return self._m

        def add_message(self, message):
            self._m.append(message)

    class _Engine:
        def __init__(self, messages, spoke=False):
            self.context = _Context(messages)
            self._speech_playback_started = asyncio.Event()
            if spoke:
                self._speech_playback_started.set()

        async def queue_node_opening(self, **kwargs):
            opened.append(kwargs["node_id"])

    silent = _Engine([{"role": "system", "content": "x"}])
    calls.schedule_tester_opening(silent, "caller")
    calls.schedule_tester_opening(_Engine([{"role": "user", "content": "Bonjour"}]), "heard")
    calls.schedule_tester_opening(_Engine([], spoke=True), "spoke")
    await asyncio.sleep(0.05)
    assert opened == ["caller"]
    assert silent.context.get_messages()[-1] == {"role": "user", "content": calls.OPENING_CUE}


@pytest.mark.asyncio
async def test_claim_by_arrival_order(config_store, monkeypatch):
    from api.brand import db as brand_db

    async def by_prefix(org, prefix, limit=50):
        return [v for (o, k), v in config_store.items() if o == org and k.startswith(prefix)]

    monkeypatch.setattr(brand_db, "list_configurations_by_prefix", by_prefix)
    for token, definition in (("aaaaaaaaaaa1", 41), ("aaaaaaaaaaa2", 42)):
        await calls.register_call(
            7, token, {"workflow_id": 3, "definition_id": definition, "agent_run_name": f"n{definition}", "test": {}}
        )
    config_store[(7, calls.CALL_PREFIX + "aaaaaaaaaaa2")]["created_at"] = "1999-01-01T00:00:00+00:00"
    # Default pairing (CallerID name): a call without token is an ordinary call.
    assert await calls.claim_inbound(7, "Jean", "790") is None
    await campaigns.save_settings(7, {"pairing": "arrival_order"})
    first = await calls.claim_inbound(7, "Jean", "790")
    assert first["definition_id"] == 41  # the oldest pending call
    assert await calls.claim_inbound(7, "Jean", "790") is None  # the other one is too old


@pytest.mark.asyncio
async def test_caller_side_of_a_phone_test_is_dropped(monkeypatch):
    from api.brand import db as brand_db
    from api.brand import test_runs
    from api.services.call_concurrency import call_concurrency

    deleted, released = [], []

    async def no_wait(_):
        return None

    async def delete(org, run_id):
        deleted.append((org, run_id))
        return True

    async def release(run_id):
        released.append(run_id)
        return True

    monkeypatch.setattr(test_runs.asyncio, "sleep", no_wait)
    monkeypatch.setattr(brand_db, "delete_test_caller_run", delete)
    monkeypatch.setattr(call_concurrency, "unregister_active_call", release)
    await test_runs._drop_caller_run(4, 99)
    assert deleted == [(4, 99)] and released == [99]


class _TransferEngine:
    def __init__(self, tools_mode="simulated", test=True):
        self._call_context_vars = {"oxee_test": {"tools_mode": tools_mode}} if test else {}
        self.recorded = {}

    def record_context(self, values):
        self.recorded.update(values)


def test_transfer_tools_are_simulated_in_test_calls():
    from types import SimpleNamespace

    tool = SimpleNamespace(name="Transfert standard", definition={"config": {"destination": "PJSIP/100"}})
    engine = _TransferEngine()
    result = calls.simulated_transfer(engine, tool, {"motif": "facturation"})
    assert result["action"] == "destination_answered" and result["simulated"] is True
    assert engine.recorded[calls.TRANSFER_CONTEXT_KEY]["destination"] == "PJSIP/100"
    assert calls.simulated_transfer(_TransferEngine("real"), tool, {}) is None
    assert calls.simulated_transfer(_TransferEngine(test=False), tool, {}) is None


def test_http_tool_transfer_flagged_by_the_simulator():
    from types import SimpleNamespace

    tool = SimpleNamespace(name="transfer_to_switchboard", definition={"config": {"url": "https://pbx/transfer"}})
    engine = _TransferEngine()
    result = {"status": "success", "oxee_transfer": True}
    assert calls.transfer_by_tool(engine, tool, {}, result) is True
    assert "oxee_transfer" not in result  # not shown to the agent
    assert engine.recorded[calls.TRANSFER_CONTEXT_KEY]["tool"] == "transfer_to_switchboard"
    assert calls.transfer_by_tool(engine, tool, {}, {"status": "success"}) is False


def test_transfer_completes_the_expected_end():
    checks = runs.deterministic_checks(
        {"expected_end_node": "Fin d'appel"},
        {"end_node": "Accueil", "transfer": {"tool": "Transfert standard"}, "tools": []},
    )
    assert checks[0]["pass"] is True and "transferred" in checks[0]["detail"]


def test_template_variables_for_the_pre_call_lookup():
    graph = {"nodes": [
        {"data": {"prompt": "Patient : {{patient_name}} ({{ account_id }}). Il est {{current_time}}.", "greeting": "Bonjour {{patient_name}}"}},
        {"data": {"prompt": "{{gathered_context.city}} {{caller_number}} {{oxee_tester_prompt}}"}},
    ]}
    assert calls.template_variables(graph, {"caller_number": "0600"}) == ["patient_name", "account_id"]


@pytest.mark.asyncio
async def test_pre_call_lookup_is_simulated_in_test_calls(monkeypatch):
    from api.brand import llm

    async def model(org):
        return {"base_url": "http://llm", "model": "m"}

    seen = {}

    async def chat_json(model, prompt, payload, **kw):
        seen.update(payload)
        return {"initial_context": {"patient_name": "Paul Bernard", "unknown": "x", "account_id": ""}}

    monkeypatch.setattr(calls, "_call_model", model)
    monkeypatch.setattr(llm, "chat_json", chat_json)
    graph = {"nodes": [{"data": {"prompt": "{{patient_name}} {{account_id}}"}}]}
    ctx = {"oxee_test": {"tools_mode": "simulated", "caller": {"name": "Paul Bernard"}}, "caller_number": "0612"}
    assert await calls.pre_call_override(ctx, graph, 1) == {"patient_name": "Paul Bernard"}
    assert seen["variables"] == ["patient_name", "account_id"] and seen["caller"]["number"] == "0612"
    assert await calls.pre_call_override({"oxee_test": {"tools_mode": "real"}}, graph, 1) is None
    assert await calls.pre_call_override({}, graph, 1) is None

    async def real():
        return {"from": "real"}

    assert await calls.pre_call_or(real(), {}, graph, 1) == {"from": "real"}
    assert await calls.pre_call_or(real(), ctx, graph, 1) == {"patient_name": "Paul Bernard"}


@pytest.mark.asyncio
async def test_new_instructions_revise_the_scenarios(monkeypatch):
    from types import SimpleNamespace

    from api.brand import analysis, llm
    from api.brand import db as brand_db
    from api.db import db_client

    def scenario(sid, edited=False):
        return {
            "id": sid, "title": f"Old {sid}", "intent": "rdv", "levels": {"mood": 4}, "speed": 1.1,
            "voice": {"id": "fr_lea", "gender": "female"}, "caller_number": "0600", "enabled": sid != "b",
            "persona": {"name": "Léa Martin", "gender": "female"}, "goal": "old", "behaviour": "", "facts": {},
            "criteria": ["c"], "forbidden": [], "expected_end_node": None, "expected_variables": {},
            "expected_tools": [], "tool_hints": "", **({"edited_at": "x"} if edited else {}),
        }

    store = {"c1": {"id": "c1", "workflow_id": 3, "language": "French", "status": "ready", "instructions": "new",
                    "scenarios": [scenario("a"), scenario("b"), scenario("c", edited=True)]}}
    seen = {}

    async def get(org, cid):
        return store.get(cid)

    async def save(org, c):
        store[c["id"]] = c
        return c

    async def chat_json(model, prompt, payload, **kw):
        seen.update(payload)
        return {"scenarios": [{"id": s["id"], "title": f"New {s['id']}", "goal": "billing", "criteria": ["transfers"],
                               "persona": {"name": "Léa Martin", "gender": "female"}} for s in payload["scenarios"]]}

    async def model(org):
        return {"model": "m"}

    async def workflow(wid, organization_id=None):
        return SimpleNamespace(id=3, name="Agent", released_definition_id=7)

    async def no_draft(wid):
        return None

    async def version(wid, did):
        return SimpleNamespace(workflow_json={"nodes": []}, workflow_configurations={})

    async def tool_names(org, uuids):
        return []

    monkeypatch.setattr(campaigns, "get", get)
    monkeypatch.setattr(campaigns, "save", save)
    monkeypatch.setattr(campaigns, "_tool_names", tool_names)
    monkeypatch.setattr(llm, "chat_json", chat_json)
    monkeypatch.setattr(analysis, "resolve_analysis_model", model)
    monkeypatch.setattr(db_client, "get_workflow", workflow)
    monkeypatch.setattr(db_client, "get_draft_version", no_draft)
    monkeypatch.setattr(brand_db, "get_workflow_version", version)

    await campaigns.rewrite(1, "c1", "old", keep_edited=True)
    c = store["c1"]
    a, b, kept = c["scenarios"]
    assert seen["new_instructions"] == "new" and seen["previous_instructions"] == "old"
    assert [s["id"] for s in seen["scenarios"]] == ["a", "b"]  # c was edited by hand
    assert (a["title"], a["goal"], a["criteria"]) == ("New a", "billing", ["transfers"])
    assert a["levels"] == {"mood": 4} and a["voice"]["id"] == "fr_lea" and a["caller_number"] == "0600"
    assert b["enabled"] is False and b["rewritten_at"]
    assert kept["title"] == "Old c"
    assert c["status"] == "ready" and c["generation"]["done"] == 2 and not c["generation"]["error"]


def test_simulated_tools_get_time_to_answer():
    engine = _TransferEngine()
    assert calls.tool_timeout(engine, 1.0) == calls.SIMULATED_TOOL_TIMEOUT + 2.0
    assert calls.tool_timeout(engine, 30.0) == 30.0
    assert calls.tool_timeout(_TransferEngine("real_with_header"), 1.0) == 1.0
    assert calls.tool_timeout(_TransferEngine(test=False), 1.0) == 1.0


def test_agent_transfer_is_recorded_with_its_destination():
    from types import SimpleNamespace

    engine = _TransferEngine()
    tool = SimpleNamespace(name="Service facturation", definition={"config": {"workflow_id": 7, "message": "Je vous passe le service."}})
    assert calls.simulated_transfer(engine, tool, {})["status"] == "success"
    assert engine.recorded[calls.TRANSFER_CONTEXT_KEY]["agent"] == 7


def test_mcp_tool_described_for_the_simulator():
    from types import SimpleNamespace

    from api.services.workflow.pipecat_engine_custom_tools import _mcp_tool_description

    schema = SimpleNamespace(name="mcp__crm__lookup", description="Find a customer", properties={"phone": {"type": "string"}})
    session = SimpleNamespace(function_schemas=lambda allowed: [schema])
    tool = _mcp_tool_description(session, "mcp__crm__lookup")
    assert tool.description == "Find a customer" and tool.definition["config"]["parameters"]["phone"]
    assert _mcp_tool_description(session, "other") is None
