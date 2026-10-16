"""OxeePhone: quality and technical score of every call, home page KPIs."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from api.brand import call_overview, call_scoring
from tests.brand.test_insights import _run


@pytest.fixture
def scoring_env(monkeypatch):
    from api.brand import analysis, analysis_thresholds, llm
    from api.brand import db as brand_db
    from api.db import db_client

    run = _run("run8.json", 1, "Accueil cabinet Martin")
    saved = {}

    async def run_by_id(run_id):
        return SimpleNamespace(id=run_id, name="WR-1", workflow_id=1, annotations=saved.get("annotations") or {})

    async def workflow_by_id(wid):
        return SimpleNamespace(organization_id=1)

    async def runs_by_ids(ids, organization_id):
        return [run]

    async def graphs(ids, organization_id):
        return {1: {"workflow_name": "Accueil", "workflow_json": {"nodes": [], "edges": []}}}

    async def model(org):
        return {"model": "judge"}

    async def judge(model, prompt, payload, **kw):
        saved["payload"] = payload
        return {"scores": {"understanding": 5, "accuracy": 4, "concision": 3, "tone": 5, "resolution": 4, "other": 1},
                "resolved": True, "summary": "Rendez-vous pris.", "issues": ["Réponses un peu longues."]}

    async def thresholds(org):
        from api.brand.analysis_thresholds import DEFAULTS

        return {"values": DEFAULTS}

    async def update(run_id, **kw):
        saved.update(kw)

    monkeypatch.setattr(db_client, "get_workflow_run_by_id", run_by_id)
    monkeypatch.setattr(db_client, "get_workflow_by_id", workflow_by_id)
    monkeypatch.setattr(db_client, "update_workflow_run", update)
    monkeypatch.setattr(brand_db, "get_runs_by_ids", runs_by_ids)
    monkeypatch.setattr(brand_db, "get_definition_graphs", graphs)
    monkeypatch.setattr(analysis, "resolve_analysis_model", model)
    monkeypatch.setattr(analysis_thresholds, "load", thresholds)
    monkeypatch.setattr(llm, "chat_json", judge)
    return saved


@pytest.mark.asyncio
async def test_a_finished_call_gets_both_scores(scoring_env):
    result = await call_scoring.score_run(8)
    assert result["quality"]["score"] == 4.2 and result["quality"]["resolved"] is True
    assert "other" not in result["quality"]["scores"]
    assert 1 <= result["technical"]["score"] <= 5 and result["technical"]["posts"]
    assert scoring_env["annotations"]["oxee_score"] is result
    assert scoring_env["payload"]["transcript"]  # the judge read the call
    # Already scored: kept unless forced.
    assert await call_scoring.score_run(8) is result


@pytest.mark.asyncio
async def test_test_calls_are_not_scored(monkeypatch):
    from api.db import db_client

    async def run_by_id(run_id):
        return SimpleNamespace(id=run_id, name="OXEE-TEST-abc-1-agent", workflow_id=1, annotations={})

    monkeypatch.setattr(db_client, "get_workflow_run_by_id", run_by_id)
    assert await call_scoring.score_run(9) is None


def test_overview_kpis():
    tz = ZoneInfo("Europe/Paris")
    now = datetime(2026, 10, 16, 15, 0, tzinfo=UTC)

    def run(hours_ago, quality=None, technical=None, resolved=True):
        score = {"quality": {"score": quality, "resolved": resolved}, "technical": {"score": technical}} if quality else None
        return {"created_at": now - timedelta(hours=hours_ago), "is_completed": True, "score": score, "duration": 120}

    runs = [run(1, 4.0, 5.0), run(2, 3.0, 4.0, resolved=False), run(3), run(30, 2.0, 3.0), run(24 * 10, 5.0, 5.0)]
    out = call_overview.summarize(runs, tz, now)
    assert out["today"]["calls"] == 3 and out["today"]["scored"] == 2
    assert out["today"]["quality"] == 3.5 and out["today"]["technical"] == 4.5
    assert out["today"]["resolved_rate"] == 0.5 and out["today"]["minutes"] == 6.0
    assert out["yesterday"]["calls"] == 1 and out["yesterday"]["quality"] == 2.0
    assert out["week"]["calls"] == 4 and len(out["daily"]) == 7
    assert out["unscored"] == 1
