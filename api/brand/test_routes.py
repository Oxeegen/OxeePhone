"""Test campaign routes, mounted under /api/v1/oxee/tests."""

from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from api.brand import test_campaigns as campaigns
from api.brand import test_runs as runs
from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user_with_selected_organization

router = APIRouter(prefix="/tests", tags=["oxeephone-tests"])


def _execution_summary(e: dict) -> dict:
    report = e.get("report") or {}
    calls = e.get("calls") or []
    return {
        **{
            k: e.get(k)
            for k in (
                "id",
                "campaign_id",
                "workflow_id",
                "definition_id",
                "version_number",
                "version_status",
                "channel",
                "passes",
                "personas",
                "status",
                "error",
                "created_at",
                "started_at",
                "finished_at",
                "created_by",
            )
        },
        "progress": {
            "total": len(calls),
            "finished": sum(
                1 for c in calls if c.get("status") in ("done", "error", "cancelled")
            ),
            "running": sum(
                1 for c in calls if c.get("status") in ("running", "judging")
            ),
        },
        "pass_rate": report.get("pass_rate"),
        "score": report.get("score"),
        "verdicts": report.get("verdicts"),
        "latency_p50_ms": (report.get("latency") or {}).get("p50_ms"),
        "quality_score": report.get("quality_score"),
        "technical_score": (report.get("technical") or {}).get("score"),
    }


def _campaign_summary(c: dict, executions: list[dict]) -> dict:
    mine = [e for e in executions if e.get("campaign_id") == c["id"]]
    done = [e for e in mine if e.get("status") == "done"]
    return {
        **{
            k: c.get(k)
            for k in (
                "id",
                "name",
                "workflow_id",
                "workflow_name",
                "status",
                "generation",
                "count",
                "tools_mode",
                "language",
                "created_at",
                "updated_at",
                "created_by",
            )
        },
        "scenarios": len(c.get("scenarios") or []),
        "executions": len(mine),
        "last_execution": _execution_summary(mine[0]) if mine else None,
        "previous_done": _execution_summary(done[1]) if len(done) > 1 else None,
        "last_done": _execution_summary(done[0]) if done else None,
    }


async def _campaign_or_404(org: int, campaign_id: str) -> dict:
    campaign = await campaigns.get(org, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Test campaign not found")
    return campaign


async def _execution_or_404(org: int, execution_id: str) -> dict:
    execution = await runs.get(org, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Test execution not found")
    return runs.stale(execution)


# --- Settings -----------------------------------------------------------------------


class TestSettingsRequest(BaseModel):
    tester_telephony_configuration_id: int | None = None
    test_inbound_number: str | None = None
    caller_numbers: list[str] | None = None
    voices: list[dict[str, Any]] | None = None
    concurrency: int | None = Field(default=None, ge=1, le=10)
    pairing: Literal["caller_name", "arrival_order"] | None = None


@router.get("/settings")
async def get_test_settings(
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Test settings of the organization, with its telephony configurations."""
    org = user.selected_organization_id
    configs = await db_client.list_telephony_configurations(org)
    return {
        "settings": await campaigns.get_settings(org),
        "telephony_configurations": [
            {"id": c.id, "name": c.name, "provider": c.provider} for c in configs
        ],
        "dimensions": {
            k: {"label": d["label"], "levels": d["levels"]}
            for k, d in campaigns.DIMENSIONS.items()
        },
        "default_ranges": campaigns.DEFAULT_RANGES,
        "default_speed": campaigns.DEFAULT_SPEED,
        "speed_limits": campaigns.SPEED_LIMITS,
    }


@router.put("/settings")
async def save_test_settings(
    request: TestSettingsRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    org = user.selected_organization_id
    changes = request.model_dump(exclude_unset=True)
    config_id = changes.get("tester_telephony_configuration_id")
    if config_id and not await db_client.get_telephony_configuration_for_org(
        config_id, org
    ):
        raise HTTPException(status_code=404, detail="Telephony configuration not found")
    return await campaigns.save_settings(org, changes)


@router.get("/phone-check")
async def check_phone_setup(
    workflow_id: int,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Whether a phone execution can start for this agent, and where it calls."""
    try:
        return {
            "ok": True,
            **await runs.check_phone_setup(user.selected_organization_id, workflow_id),
        }
    except runs.ExecutionError as e:
        return {"ok": False, "error": str(e)}


# --- Campaigns --------------------------------------------------------------------------


class CreateCampaignRequest(BaseModel):
    name: str = ""
    workflow_id: int
    ranges: dict[str, list[int]] | None = None
    speed: list[float] | None = None
    count: int = Field(default=30, ge=1, le=campaigns.MAX_SCENARIOS)
    language: str = "English"
    tools_mode: Literal["simulated", "real", "real_with_header"] = "simulated"
    max_duration_seconds: int = Field(default=300, ge=60, le=900)
    instructions: str | None = None


@router.get("/campaigns")
async def list_test_campaigns(
    user: UserModel = Depends(get_user_with_selected_organization),
):
    org = user.selected_organization_id
    executions = await runs.list_executions(org)
    return [
        _campaign_summary(c, executions) for c in await campaigns.list_campaigns(org)
    ]


@router.post("/campaigns")
async def create_test_campaign(
    request: CreateCampaignRequest,
    background_tasks: BackgroundTasks,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Create a campaign; its scenarios are written in the background by the
    analysis model (poll GET /tests/campaigns/{id})."""
    org = user.selected_organization_id
    try:
        campaign = await campaigns.create(org, user, **request.model_dump())
    except campaigns.CampaignError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    background_tasks.add_task(campaigns.generate, org, campaign["id"])
    return campaign


@router.get("/campaigns/{campaign_id}")
async def get_test_campaign(
    campaign_id: str,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    org = user.selected_organization_id
    campaign = await _campaign_or_404(org, campaign_id)
    executions = await runs.list_executions(org, campaign_id=campaign_id)
    return {
        **campaign,
        "executions": [_execution_summary(runs.stale(e)) for e in executions],
    }


class UpdateCampaignRequest(BaseModel):
    name: str | None = None
    language: str | None = None
    tools_mode: Literal["simulated", "real", "real_with_header"] | None = None
    max_duration_seconds: int | None = Field(default=None, ge=60, le=900)
    instructions: str | None = None
    ranges: dict[str, list[int]] | None = None
    speed: list[float] | None = None


@router.patch("/campaigns/{campaign_id}")
async def update_test_campaign(
    campaign_id: str,
    request: UpdateCampaignRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Campaign settings. Ranges and speed apply to scenarios written next."""
    org = user.selected_organization_id
    campaign = await _campaign_or_404(org, campaign_id)
    changes = request.model_dump(exclude_unset=True)
    try:
        if "ranges" in changes:
            changes["ranges"] = campaigns.normalize_ranges(changes["ranges"])
        if "speed" in changes:
            changes["speed"] = campaigns.normalize_speed(changes["speed"])
    except campaigns.CampaignError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if "name" in changes:
        changes["name"] = (changes["name"] or "").strip()[:120] or campaign["name"]
    campaign.update(changes)
    return await campaigns.save(org, campaign)


@router.delete("/campaigns/{campaign_id}")
async def delete_test_campaign(
    campaign_id: str,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Delete a campaign and its executions (the calls stay in the run history)."""
    org = user.selected_organization_id
    await _campaign_or_404(org, campaign_id)
    for e in await runs.list_executions(org, campaign_id=campaign_id):
        if e.get("status") in ("queued", "running"):
            raise HTTPException(status_code=409, detail="An execution is running")
    for e in await runs.list_executions(org, campaign_id=campaign_id):
        await runs.delete(org, e["id"])
    await campaigns.delete(org, campaign_id)
    return {"deleted": True}


class GenerateMoreRequest(BaseModel):
    count: int = Field(default=5, ge=1, le=campaigns.MAX_SCENARIOS)


@router.post("/campaigns/{campaign_id}/generate")
async def generate_more_scenarios(
    campaign_id: str,
    request: GenerateMoreRequest,
    background_tasks: BackgroundTasks,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Write more scenarios with the campaign's current ranges."""
    org = user.selected_organization_id
    campaign = await _campaign_or_404(org, campaign_id)
    if campaign.get("status") == "generating":
        raise HTTPException(status_code=409, detail="Scenarios are being written")
    total = min(campaigns.MAX_SCENARIOS, len(campaign["scenarios"]) + request.count)
    if total <= len(campaign["scenarios"]):
        raise HTTPException(
            status_code=422,
            detail=f"A campaign holds at most {campaigns.MAX_SCENARIOS} scenarios",
        )
    campaign.update(count=total, status="generating")
    await campaigns.save(org, campaign)
    background_tasks.add_task(campaigns.generate, org, campaign_id)
    return campaign


@router.patch("/campaigns/{campaign_id}/scenarios/{scenario_id}")
async def update_test_scenario(
    campaign_id: str,
    scenario_id: str,
    changes: dict[str, Any],
    user: UserModel = Depends(get_user_with_selected_organization),
):
    org = user.selected_organization_id
    campaign = await _campaign_or_404(org, campaign_id)
    try:
        scenario = campaigns.update_scenario(campaign, scenario_id, changes)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await campaigns.save(org, campaign)
    return scenario


class DuplicateScenarioRequest(BaseModel):
    levels: dict[str, int] | None = None


@router.post("/campaigns/{campaign_id}/scenarios/{scenario_id}/duplicate")
async def duplicate_test_scenario(
    campaign_id: str,
    scenario_id: str,
    request: DuplicateScenarioRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """A variant of a scenario (same request, other caller levels)."""
    org = user.selected_organization_id
    campaign = await _campaign_or_404(org, campaign_id)
    try:
        variant = campaigns.duplicate_scenario(campaign, scenario_id, request.levels)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except campaigns.CampaignError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await campaigns.save(org, campaign)
    return variant


@router.delete("/campaigns/{campaign_id}/scenarios/{scenario_id}")
async def delete_test_scenario(
    campaign_id: str,
    scenario_id: str,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    org = user.selected_organization_id
    campaign = await _campaign_or_404(org, campaign_id)
    before = len(campaign["scenarios"])
    campaign["scenarios"] = [s for s in campaign["scenarios"] if s["id"] != scenario_id]
    if len(campaign["scenarios"]) == before:
        raise HTTPException(status_code=404, detail="Scenario not found")
    campaign["count"] = len(campaign["scenarios"])
    await campaigns.save(org, campaign)
    return {"deleted": True}


# --- Executions --------------------------------------------------------------------------


class RunCampaignRequest(BaseModel):
    version: str | int = "published"
    channel: Literal["phone", "text"] = "phone"
    passes: int = Field(default=1, ge=1, le=10)
    personas: Literal["frozen", "fresh"] = "frozen"
    concurrency: int | None = Field(default=None, ge=1, le=10)
    scenario_ids: list[str] | None = None


@router.post("/campaigns/{campaign_id}/executions")
async def run_test_campaign(
    campaign_id: str,
    request: RunCampaignRequest,
    background_tasks: BackgroundTasks,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Play the campaign on a version of the agent ("published", "draft" or a
    version id), by phone or as text. Runs in the background, one execution at
    a time: poll GET /tests/executions/{id}."""
    org = user.selected_organization_id
    campaign = await _campaign_or_404(org, campaign_id)
    try:
        execution = await runs.create_execution(
            org,
            user,
            campaign,
            version=request.version,
            channel=request.channel,
            passes=request.passes,
            personas=request.personas,
            concurrency=request.concurrency,
            scenario_ids=request.scenario_ids,
        )
    except runs.ExecutionError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    background_tasks.add_task(runs.run, org, execution["id"], user.id)
    return _execution_summary(execution)


@router.get("/executions/{execution_id}")
async def get_test_execution(
    execution_id: str,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    return await _execution_or_404(user.selected_organization_id, execution_id)


@router.post("/executions/{execution_id}/cancel")
async def cancel_test_execution(
    execution_id: str,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Stop starting new calls; calls in progress finish and are judged."""
    org = user.selected_organization_id
    execution = await _execution_or_404(org, execution_id)
    if execution["status"] not in ("queued", "running"):
        raise HTTPException(
            status_code=409, detail=f"Execution is {execution['status']}"
        )
    runs.cancel(execution_id)
    if execution["status"] == "queued" or execution.get("status") == "interrupted":
        execution.update(status="cancelled")
        await runs.save(org, execution)
    return _execution_summary(execution)


@router.delete("/executions/{execution_id}")
async def delete_test_execution(
    execution_id: str,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    org = user.selected_organization_id
    execution = await _execution_or_404(org, execution_id)
    if execution["status"] in ("queued", "running"):
        raise HTTPException(status_code=409, detail="Cancel the execution first")
    await runs.delete(org, execution_id)
    return {"deleted": True}


@router.post("/executions/{execution_id}/recompute")
async def recompute_test_execution(
    execution_id: str,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Recompute the report (after a change of the report rules)."""
    from api.brand.analysis import _graph_index

    org = user.selected_organization_id
    execution = await _execution_or_404(org, execution_id)
    graphs = await runs.brand_db.get_definition_graphs(
        [execution["definition_id"]], organization_id=org
    )
    from api.brand.analysis_thresholds import load as load_thresholds
    from api.brand.test_technical import call_technical

    thresholds = (await load_thresholds(org))["values"]
    for call in execution["calls"]:
        if call.get("metrics"):
            call["technical"] = call_technical(
                call, thresholds, channel=execution["channel"]
            )
    index = _graph_index(graphs).get(execution["definition_id"])
    snapshot = execution.get("definition_snapshot")
    if index is None and snapshot:  # the draft tested was discarded since
        index = _graph_index(
            {
                execution["definition_id"]: {
                    "workflow_name": execution["workflow_name"],
                    "workflow_json": snapshot.get("workflow_json") or {},
                }
            }
        ).get(execution["definition_id"])
    previous = execution.get("report") or {}
    execution["report"] = runs.aggregate(execution, index, thresholds)
    if index is None and previous.get("coverage"):
        execution["report"]["coverage"] = previous["coverage"]
    return await runs.save(org, execution)


@router.get("/compare")
async def compare_test_executions(
    a: str,
    b: str,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Execution ``b`` against execution ``a``: indicators, scenario outcomes,
    coverage and the configuration diff between the two versions."""
    try:
        return await runs.compare(user.selected_organization_id, a, b)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class FixFromCallRequest(BaseModel):
    language: str = "English"


@router.post("/executions/{execution_id}/calls/{call_index}/fix")
async def fix_from_test_call(
    execution_id: str,
    call_index: int,
    request: FixFromCallRequest,
    background_tasks: BackgroundTasks,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Ask for an automatic fix of a failed test call (see the fixes routes)."""
    from api.brand import fixes

    org = user.selected_organization_id
    execution = await _execution_or_404(org, execution_id)
    call = next((c for c in execution["calls"] if c["index"] == call_index), None)
    if call is None:
        raise HTTPException(status_code=404, detail="Call not found")
    if call.get("verdict") not in ("fail", "partial"):
        raise HTTPException(status_code=409, detail="Only a failed call can be fixed")
    if call.get("fix_id"):
        existing = await fixes.get(org, call["fix_id"])
        if existing and existing.get("status") in fixes.ACTIVE:
            return existing
    finding = runs.finding_from_call(execution, call)
    report = {"id": f"test:{execution_id}", "workflow_id": execution["workflow_id"]}
    fix = await fixes.create(org, user, report, finding, language=request.language)
    call["fix_id"] = fix["id"]
    await runs.save(org, execution)
    if fix["status"] == "proposing":
        background_tasks.add_task(fixes.propose, org, fix["id"])
    return fix
