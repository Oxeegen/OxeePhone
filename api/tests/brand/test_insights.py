"""OxeePhone reporting insights, computed on two real calls (scrubbed fixtures
shared with the UI tests): #8 (tool call) and #10 (routing)."""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from api.brand.insights import compute_insights, latency_turn, period_bounds

FIXTURES = Path(__file__).resolve().parents[3] / "ui/src/brand/call-detail/__fixtures__"
PARIS = ZoneInfo("Europe/Paris")


def _run(name: str, definition_id: int, workflow: str) -> dict:
    raw = json.loads((FIXTURES / name).read_text())
    return {
        "id": raw["id"],
        "workflow_id": definition_id,
        "workflow_name": workflow,
        "definition_id": definition_id,
        "created_at": datetime.fromisoformat(raw["created_at"].replace("Z", "+00:00")),
        "is_completed": raw["is_completed"],
        "mode": raw["mode"],
        "usage_info": raw["usage_info"],
        "gathered_context": raw["gathered_context"],
        "logs": raw["logs"],
    }


def _graphs() -> dict:
    routing = json.loads((FIXTURES / "run10-routing.json").read_text())["graphs"][0]
    return {
        4: {
            "workflow_json": {
                "nodes": [
                    {"id": n["id"], "data": {"name": n["name"]}}
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
            }
        }
    }


@pytest.fixture(scope="module")
def insights():
    runs = [
        _run("run8.json", 1, "Accueil cabinet Martin"),
        _run("run10.json", 4, "Cabinet Martin — routage"),
    ]
    return compute_insights(runs, _graphs(), tz=PARIS)


def test_volume_and_quality(insights):
    assert insights["calls"]["total"] == 2
    assert insights["calls"]["completed"] == 2
    assert insights["calls"]["total_minutes"] > 2
    assert insights["conversation"]["interruption_rate"] > 0
    assert {"reason": "end_call", "count": 1} in insights["conversation"]["end_reasons"]


def test_latency(insights):
    lat = insights["latency"]
    assert lat["turns"] >= 8
    assert lat["p50_ms"] <= lat["p90_ms"]
    assert 0 <= lat["slow_share"] <= 1
    assert lat["greeting_avg_ms"] < 1000
    assert lat["llm_first_token_avg_ms"] < lat["stages"]["llm"]


def test_usage(insights):
    usage = insights["usage"]
    assert usage["prompt_tokens"] >= 4290
    assert 0 < usage["cache_hit_rate"] < 1
    assert usage["models"][0]["model"] == "Oxee-flash"
    assert usage["tts_characters"] > 0
    assert usage["caller_speech_minutes"] > 0


def test_tools_exclude_node_transitions(insights):
    names = {t["name"] for t in insights["tools"]}
    assert "check_availability" in names
    assert not names & {"prise_de_rendez_vous", "rendez_vous_confirm_"}
    check = next(t for t in insights["tools"] if t["name"] == "check_availability")
    assert check["calls"] == 2 and check["errors"] == 0


def test_routing(insights):
    pathways = {
        (p["from"], p["to"]): p["count"] for p in insights["routing"]["pathways"]
    }
    assert pathways[("Accueil", "Prise de rendez-vous")] == 1
    assert pathways[("Prise de rendez-vous", "Fin d'appel")] == 1


def test_daily_series(insights):
    assert [d["date"] for d in insights["daily"]] == ["2026-09-30"]
    assert insights["daily"][0]["calls"] == 2


def test_period_bounds_follow_local_days():
    start, end = period_bounds("2026-09-30", 7, PARIS)
    assert start.isoformat() == "2026-09-23T22:00:00+00:00"
    assert end.isoformat().startswith("2026-09-30T21:59:59")


def test_tool_failure_detection():
    from api.brand.insights import _tool_failed

    assert _tool_failed("{'status': 'error', 'message': 'x'}")
    assert _tool_failed({"status": "success", "status_code": 502})
    assert not _tool_failed("{'status': 'success', 'status_code': 200}")


def test_latency_turn_matches_ui_model():
    payload = {
        "total_secs": 2.0,
        "measured_from": "user_silence",
        "contributions": [
            {"key": "endpointing_wait", "start_time": 0.0, "duration_secs": 0.2},
            {"key": "transcription", "start_time": 0.2, "duration_secs": 0.3},
        ],
        "ttfb": [
            {
                "processor": "SpeachesLLMService#0",
                "start_time": 0.5,
                "duration_secs": 0.3,
            },
            {
                "processor": "LocalModelsTTSService#0",
                "start_time": 1.6,
                "duration_secs": 0.4,
            },
        ],
        "function_calls": [],
        "text_aggregation": {"duration_secs": 0.1},
    }
    turn = latency_turn(payload)
    assert turn["stages"]["llm"] == pytest.approx(
        1000, abs=1
    )  # 0.5 -> 1.6 minus 100 ms sentence
    assert turn["stages"]["voice"] == pytest.approx(400)
    assert sum(turn["stages"].values()) == pytest.approx(turn["total_ms"], abs=1)


def test_pipeline_error_status_counts_as_error_call():
    run = _run("run8.json", 1, "Accueil cabinet Martin")
    run["gathered_context"] = {
        **run["gathered_context"],
        "call_status": "pipeline_error",
    }
    assert compute_insights([run], {}, tz=PARIS)["calls"]["with_errors"] == 1
