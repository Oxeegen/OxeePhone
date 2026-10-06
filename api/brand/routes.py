"""OxeePhone API routes, mounted under /api/v1/oxee."""

from datetime import datetime
from typing import Literal

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from api.brand.config import BRAND
from api.brand.local_models import (
    LocalModelsError,
    list_endpoint_models,
    resolve_api_key,
    synthesize_preview,
)
from api.db.models import UserModel
from api.services.auth.depends import get_user_with_selected_organization
from api.services.configuration.ai_model_configuration import (
    get_organization_ai_model_configuration_v2,
)

router = APIRouter(prefix="/oxee", tags=["oxeephone"])


class EndpointModelsRequest(BaseModel):
    service: Literal["llm", "tts", "stt", "embeddings", "analysis"]
    base_url: str
    api_key: str | None = None


class EndpointModelsResponse(BaseModel):
    models: list[str]


@router.post("/models", response_model=EndpointModelsResponse)
async def list_models(
    request: EndpointModelsRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """List the models served by an OpenAI-compatible endpoint (GET /models).

    A masked key (as displayed by the Models page) is swapped for the stored
    organization key it masks.
    """
    stored = await get_organization_ai_model_configuration_v2(
        user.selected_organization_id
    )
    if request.service == "analysis":
        from api.brand.analysis import MODEL_KEY
        from api.db import db_client
        from api.services.configuration.masking import MASK_MARKER, is_mask_of

        row = await db_client.get_configuration(
            user.selected_organization_id, MODEL_KEY
        )
        real = ((row.value if row else None) or {}).get("api_key")
        api_key = request.api_key
        if api_key and MASK_MARKER in api_key:
            api_key = real if real and is_mask_of(api_key, real) else None
    else:
        api_key = resolve_api_key(request.api_key, stored, request.service)
    try:
        models = await list_endpoint_models(request.base_url, api_key)
    except LocalModelsError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return EndpointModelsResponse(models=models)


class VoicePreviewRequest(BaseModel):
    base_url: str
    api_key: str | None = None
    model: str
    voice: str
    speed: float | None = Field(default=None, ge=0.25, le=4.0)
    language: str | None = None
    text: str | None = None
    volume_gain_db: float | None = Field(default=None, ge=-12.0, le=12.0)
    pronunciations: str | None = None


@router.post(
    "/tts/preview",
    response_class=Response,
    responses={200: {"content": {"audio/wav": {}}}},
)
async def preview_voice(
    request: VoicePreviewRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Render a WAV sample with the Voice tab's current (unsaved) settings."""
    stored = await get_organization_ai_model_configuration_v2(
        user.selected_organization_id
    )
    try:
        audio = await synthesize_preview(
            base_url=request.base_url,
            api_key=resolve_api_key(request.api_key, stored, "tts"),
            model=request.model,
            voice=request.voice,
            speed=request.speed,
            language=request.language,
            text=request.text,
            volume_gain_db=request.volume_gain_db,
            pronunciations=request.pronunciations,
        )
    except LocalModelsError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return Response(content=audio, media_type="audio/wav")


@router.get("/runs/{run_id}/routing")
async def run_routing(
    run_id: int,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Graphs (nodes, edges, conditions) used by a call, for the Routing tab."""
    from api.brand.routing import run_routing_graphs
    from api.db import db_client

    run = await db_client.get_workflow_run(
        run_id, organization_id=user.selected_organization_id
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Call not found")
    return await run_routing_graphs(run, organization_id=user.selected_organization_id)


@router.get("/reports/insights")
async def report_insights(
    date: str,
    timezone: str,
    days: int = 7,
    workflow_id: int | None = None,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Latency, consumption, quality, tools and routing indicators for the
    ``days`` local days ending on ``date`` (Reports page)."""
    from zoneinfo import ZoneInfoNotFoundError

    from api.brand.insights import get_insights

    if days not in (1, 7, 30):
        raise HTTPException(status_code=422, detail="days must be 1, 7 or 30")
    try:
        return await get_insights(
            organization_id=user.selected_organization_id,
            date=date,
            days=days,
            timezone=timezone,
            workflow_id=workflow_id,
        )
    except (ValueError, ZoneInfoNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ------------------------------------------------------------- analysis


class AnalysisModelConfig(BaseModel):
    same_as_llm: bool = True
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


@router.get("/analysis/model", response_model=AnalysisModelConfig)
async def get_analysis_model(
    user: UserModel = Depends(get_user_with_selected_organization),
):
    from api.brand.analysis import MODEL_KEY
    from api.db import db_client
    from api.services.configuration.masking import mask_key

    row = await db_client.get_configuration(user.selected_organization_id, MODEL_KEY)
    cfg = AnalysisModelConfig(**((row.value if row else None) or {}))
    if cfg.api_key:
        cfg.api_key = mask_key(cfg.api_key)
    return cfg


@router.put("/analysis/model", response_model=AnalysisModelConfig)
async def save_analysis_model(
    request: AnalysisModelConfig,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    from api.brand.analysis import MODEL_KEY
    from api.db import db_client
    from api.services.configuration.masking import MASK_MARKER, mask_key
    from api.utils.url_security import validate_user_configured_service_url

    organization_id = user.selected_organization_id
    row = await db_client.get_configuration(organization_id, MODEL_KEY)
    stored = (row.value if row else None) or {}
    api_key = request.api_key
    if api_key and MASK_MARKER in api_key:
        api_key = stored.get("api_key")  # unchanged masked key
    if not request.same_as_llm:
        if not request.base_url or not request.model:
            raise HTTPException(
                status_code=422, detail="Base URL and model are required."
            )
        try:
            validate_user_configured_service_url(
                request.base_url, field_name="base_url"
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    value = {
        "same_as_llm": request.same_as_llm,
        "base_url": (request.base_url or "").strip() or None,
        "api_key": api_key or None,
        "model": (request.model or "").strip() or None,
    }
    await db_client.upsert_configuration(organization_id, MODEL_KEY, value)
    return AnalysisModelConfig(
        **{**value, "api_key": mask_key(api_key) if api_key else None}
    )


class AnalysisRunRequest(BaseModel):
    date: str
    timezone: str
    days: int = 7
    workflow_id: int | None = None
    language: str = "English"


def _report_summary(report: dict) -> dict:
    counts: dict[str, int] = {}
    for f in report.get("findings") or []:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return {
        k: report.get(k)
        for k in (
            "id",
            "status",
            "created_at",
            "finished_at",
            "params",
            "calls_analyzed",
            "model",
            "error",
        )
    } | {"counts": counts}


@router.post("/analysis/reports")
async def start_analysis(
    request: AnalysisRunRequest,
    background_tasks: BackgroundTasks,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Start a configuration analysis over the period; poll the report."""
    from api.brand.analysis import create_report, run_analysis

    try:
        report, run_kwargs = await create_report(
            user,
            date=request.date,
            days=request.days,
            timezone=request.timezone,
            workflow_id=request.workflow_id,
            language=request.language,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    background_tasks.add_task(run_analysis, report["id"], **run_kwargs)
    return _report_summary(report)


@router.get("/analysis/reports")
async def list_analysis_reports(
    user: UserModel = Depends(get_user_with_selected_organization),
):
    from api.brand.analysis import REPORT_PREFIX
    from api.brand.db import list_configurations_by_prefix

    reports = await list_configurations_by_prefix(
        user.selected_organization_id, REPORT_PREFIX
    )
    return [_report_summary(r) for r in reports]


@router.get("/analysis/reports/{report_id}")
async def get_analysis_report(
    report_id: str,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    from api.brand.analysis import get_report

    report = await get_report(user.selected_organization_id, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.delete("/analysis/reports/{report_id}")
async def delete_analysis_report(
    report_id: str,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    from api.brand.analysis import REPORT_PREFIX
    from api.brand.db import delete_configuration

    if not await delete_configuration(
        user.selected_organization_id, REPORT_PREFIX + report_id
    ):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"deleted": True}


# --------------------------------------------------- analysis thresholds


def _thresholds_response(state: dict) -> dict:
    from api.brand.analysis_thresholds import SPEC

    return {
        "spec": SPEC,
        "values": state["values"],
        "source": state.get("source", "builtin"),
        "suggestions": state.get("suggestions") or {},
        "suggested_at": state.get("suggested_at"),
        "model": state.get("model"),
    }


@router.get("/analysis/thresholds")
async def get_analysis_thresholds(
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Detection thresholds (values in use, model suggestions, spec)."""
    from api.brand.analysis_thresholds import load

    return _thresholds_response(await load(user.selected_organization_id))


class ThresholdsUpdate(BaseModel):
    values: dict[str, float]
    source: Literal["custom", "model", "builtin"] = "custom"


@router.put("/analysis/thresholds")
async def save_analysis_thresholds(
    request: ThresholdsUpdate,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Save thresholds (clamped to their allowed ranges)."""
    from api.brand.analysis_thresholds import load, store

    state = await load(user.selected_organization_id)
    state.update(values=request.values, source=request.source)
    return _thresholds_response(await store(user.selected_organization_id, state))


class ThresholdsSuggestRequest(BaseModel):
    timezone: str = "UTC"
    language: str = "English"


@router.post("/analysis/thresholds/suggest")
async def suggest_analysis_thresholds(
    request: ThresholdsSuggestRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Ask the analysis model for thresholds suited to the agents and apply them."""
    from zoneinfo import ZoneInfoNotFoundError

    from api.brand.analysis_thresholds import suggest_for_organization

    try:
        state = await suggest_for_organization(
            user.selected_organization_id,
            timezone=request.timezone,
            language=request.language,
        )
    except ZoneInfoNotFoundError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except (RuntimeError, ValueError, httpx.HTTPError) as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return _thresholds_response(state)


# --- Agent versions ---------------------------------------------------------


async def _own_workflow(workflow_id: int, user: UserModel):
    from api.db import db_client

    workflow = await db_client.get_workflow(
        workflow_id, organization_id=user.selected_organization_id
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    return workflow


@router.get("/workflows/{workflow_id}/versions")
async def list_agent_versions(
    workflow_id: int,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Versions of an agent, newest first, each with its origin (editor, API
    key, MCP, restore, automatic fix), authors, number of calls and a short
    summary of what changed since the previous version."""
    from api.brand.versions import list_versions

    await _own_workflow(workflow_id, user)
    return await list_versions(
        workflow_id,
        organization_id=user.selected_organization_id,
        limit=limit,
        offset=offset,
    )


@router.get("/workflows/{workflow_id}/versions/{definition_id}/diff")
async def get_agent_version_diff(
    workflow_id: int,
    definition_id: int,
    base: int | None = Query(
        None, description="Version id to compare with (default: the previous version)"
    ),
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Detailed diff: every node, transition, setting and variable changed,
    with before / after values and word-level diffs of long texts."""
    from api.brand.versions import version_diff

    await _own_workflow(workflow_id, user)
    diff = await version_diff(
        workflow_id,
        definition_id,
        organization_id=user.selected_organization_id,
        base_id=base,
    )
    if diff is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return diff


class VersionSummaryRequest(BaseModel):
    base: int | None = None
    language: str = "English"


@router.post("/workflows/{workflow_id}/versions/{definition_id}/summary")
async def summarize_agent_version(
    workflow_id: int,
    definition_id: int,
    request: VersionSummaryRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Plain-language summary of the changes, written by the analysis model
    (kept with the version)."""
    from api.brand.versions import summarize

    await _own_workflow(workflow_id, user)
    try:
        return await summarize(
            workflow_id,
            definition_id,
            organization_id=user.selected_organization_id,
            base_id=request.base,
            language=request.language,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except (RuntimeError, httpx.HTTPError) as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


class RestoreVersionRequest(BaseModel):
    replace_draft: bool = False
    note: str | None = Field(default=None, max_length=500)


@router.post("/workflows/{workflow_id}/versions/{definition_id}/restore")
async def restore_agent_version(
    workflow_id: int,
    definition_id: int,
    request: RestoreVersionRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Create a draft with the content of an earlier version (graph, settings,
    variables). The published version keeps running until the draft is
    published (POST /api/v1/workflow/{id}/publish). 409 when a draft already
    exists, unless ``replace_draft``."""
    from api.brand.versions import DraftExists, restore

    await _own_workflow(workflow_id, user)
    try:
        draft = await restore(
            workflow_id,
            definition_id,
            user,
            organization_id=user.selected_organization_id,
            replace_draft=request.replace_draft,
            note=request.note,
        )
    except DraftExists as e:
        raise HTTPException(
            status_code=409,
            detail=f"Draft v{e.draft.version_number} has unpublished changes; "
            "pass replace_draft to discard it",
        ) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {
        "id": draft.id,
        "version_number": draft.version_number,
        "status": draft.status,
    }


@router.delete("/workflows/{workflow_id}/draft")
async def discard_agent_draft(
    workflow_id: int,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Throw away the unpublished draft; the published version stays."""
    from api.brand.versions import discard_draft

    await _own_workflow(workflow_id, user)
    try:
        await discard_draft(workflow_id, organization_id=user.selected_organization_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"discarded": True}


# --- Automatic fixes ----------------------------------------------------------


class CreateFixRequest(BaseModel):
    report_id: str
    finding_id: str | None = None
    language: str = "English"


def _stale(fix: dict) -> dict:
    """A fix stuck in a background step (API restarted) is marked failed."""
    from datetime import UTC, datetime, timedelta

    busy = fix.get("status") in ("proposing", "testing")
    updated = fix.get("updated_at")
    if busy and updated:
        age = datetime.now(UTC) - datetime.fromisoformat(updated)
        if age > timedelta(minutes=20):
            fix = {
                **fix,
                "status": "failed",
                "error": "interrupted (the API restarted?)",
            }
    return fix


@router.get("/fixes")
async def list_agent_fixes(
    report_id: str | None = None,
    workflow_id: int | None = None,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Automatic fixes, newest first (optionally for one analysis report or agent)."""
    from api.brand.fixes import list_fixes

    items = await list_fixes(
        user.selected_organization_id, report_id=report_id, workflow_id=workflow_id
    )
    return [_stale(f) for f in items]


@router.post("/fixes")
async def create_agent_fixes(
    request: CreateFixRequest,
    background_tasks: BackgroundTasks,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Ask the analysis model for a fix of one finding (``finding_id``) or of
    every fixable finding of the report without a fix yet. Proposals run in
    the background: poll GET /fixes/{id}."""
    from api.brand import fixes
    from api.brand.analysis import get_report

    org = user.selected_organization_id
    report = await get_report(org, request.report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    findings = report.get("findings") or []
    if request.finding_id:
        findings = [f for f in findings if f.get("id") == request.finding_id]
        if not findings:
            raise HTTPException(status_code=404, detail="Finding not found")
        live = [
            f
            for f in await fixes.list_fixes(org, report_id=request.report_id)
            if f["finding"].get("id") == request.finding_id
            and f.get("status") in fixes.ACTIVE
        ]
        if live:
            return live[:1]  # one live fix per finding
    else:
        taken = {
            f["finding"].get("id")
            for f in await fixes.list_fixes(org, report_id=request.report_id)
            if f.get("status") in fixes.ACTIVE
        }
        findings = [
            f
            for f in findings
            if f.get("id") not in taken and fixes.fixability(f)["fixable"]
        ]
    created = [
        await fixes.create(org, user, report, f, language=request.language)
        for f in findings
    ]

    async def run_proposals(ids: list[str]):
        for fix_id in ids:
            await fixes.propose(org, fix_id)

    background_tasks.add_task(
        run_proposals, [f["id"] for f in created if f["status"] == "proposing"]
    )
    return created


@router.get("/fixes/{fix_id}")
async def get_agent_fix(
    fix_id: str,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """One fix, with the diff of its proposal against the published version."""
    from api.brand import fixes

    fix = await fixes.get(user.selected_organization_id, fix_id)
    if fix is None:
        raise HTTPException(status_code=404, detail="Fix not found")
    fix = _stale(fix)
    try:
        fix["preview"] = await fixes.preview_diff(user.selected_organization_id, fix)
    except fixes.FixError as e:
        fix["preview"] = None
        fix["preview_error"] = str(e)
    return fix


@router.post("/fixes/{fix_id}/propose")
async def repropose_agent_fix(
    fix_id: str,
    background_tasks: BackgroundTasks,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Ask the model again (after a failure or to get another proposal)."""
    from api.brand import fixes

    org = user.selected_organization_id
    fix = await fixes.get(org, fix_id)
    if fix is None:
        raise HTTPException(status_code=404, detail="Fix not found")
    if fix["status"] not in ("proposed", "failed", "not_fixable"):
        raise HTTPException(status_code=409, detail=f"Fix is {fix['status']}")
    if not fix.get("workflow_id"):
        raise HTTPException(
            status_code=422, detail="The agent of this finding is unknown"
        )
    fix.update(status="proposing", error=None, reason=None, proposal=None)
    await fixes.save(org, fix)
    background_tasks.add_task(fixes.propose, org, fix_id)
    return fix


class ApplyFixRequest(BaseModel):
    replace_draft: bool = False


@router.post("/fixes/{fix_id}/apply")
async def apply_agent_fix(
    fix_id: str,
    request: ApplyFixRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Save the proposal as a draft of the agent (combined with the other
    fixes already in a fix draft). 409 when a draft made by hand exists,
    unless ``replace_draft``. The published version is untouched."""
    from api.brand import fixes, versions

    try:
        return await fixes.apply(
            user.selected_organization_id,
            fix_id,
            user,
            replace_draft=request.replace_draft,
        )
    except versions.DraftExists as e:
        raise HTTPException(
            status_code=409,
            detail=f"Draft v{e.draft.version_number} has unpublished changes made "
            "by hand; pass replace_draft to discard it",
        ) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except fixes.FixError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


class SimulateFixRequest(BaseModel):
    max_cases: int = Field(default=3, ge=1, le=5)


@router.post("/fixes/{fix_id}/simulate")
async def simulate_agent_fix(
    fix_id: str,
    request: SimulateFixRequest,
    background_tasks: BackgroundTasks,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Replay the finding's calls (or recent calls) as text on the published
    version and on the draft, then compare. Tools are not executed: their
    recorded results are replayed. Runs in the background."""
    from api.brand import fixes

    org = user.selected_organization_id
    fix = await fixes.get(org, fix_id)
    if fix is None:
        raise HTTPException(status_code=404, detail="Fix not found")
    if fix["status"] not in ("applied", "tested"):
        raise HTTPException(status_code=409, detail="Apply the fix to a draft first")
    fix.update(status="testing", simulation={"status": "starting", "cases": []})
    await fixes.save(org, fix)
    background_tasks.add_task(
        fixes.simulate, org, fix_id, user.id, max_cases=request.max_cases
    )
    return fix


@router.post("/fixes/{fix_id}/discard")
async def discard_agent_fix(
    fix_id: str,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Drop the fix (and its draft when it holds no other fix)."""
    from api.brand import fixes

    try:
        return await fixes.discard(user.selected_organization_id, fix_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except fixes.FixError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.get("/workflows/list-info")
async def agent_list_info(
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """For the agent list: last run, published version and draft of each agent
    (``{workflow_id: {last_run_at, published_version, published_at, draft_version}}``).
    """
    from api.brand.db import agent_list_info as load

    return {str(k): v for k, v in (await load(user.selected_organization_id)).items()}


@router.post("/fixes/{fix_id}/follow-up")
async def follow_up_agent_fix(
    fix_id: str,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """After publication: is the finding gone from the real calls made on the
    fixed version? (waiting / fixed / still_present / worse / manual)"""
    from api.brand import fixes

    try:
        return await fixes.follow_up(user.selected_organization_id, fix_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except fixes.FixError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


class RollbackFixRequest(BaseModel):
    replace_draft: bool = False


@router.post("/fixes/{fix_id}/rollback")
async def rollback_agent_fix(
    fix_id: str,
    request: RollbackFixRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Publish again the version the fix replaced (as a new version). Refused
    when the agent was published again since; 409 when a draft exists unless
    ``replace_draft``. Every fix of the rolled back version goes with it."""
    from api.brand import fixes, versions

    try:
        return await fixes.rollback(
            user.selected_organization_id,
            fix_id,
            user,
            replace_draft=request.replace_draft,
        )
    except versions.DraftExists as e:
        raise HTTPException(
            status_code=409,
            detail=f"Draft v{e.draft.version_number} has unpublished changes; "
            "pass replace_draft to discard it",
        ) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except fixes.FixError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.get("/releases")
async def oxeephone_releases(
    refresh: bool = False,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Current OxeePhone version, its release notes, and newer releases
    published on GitHub (checked by the server, cached for an hour)."""
    from api.brand.releases import release_info

    return await release_info(force=refresh)


class VoicePreviewRequest(BaseModel):
    voice: str = Field(min_length=1, max_length=120)
    speed: float | None = Field(default=None, ge=0.5, le=2.0)
    text: str | None = Field(default=None, max_length=300)


@router.post(
    "/voice/preview",
    response_class=Response,
    responses={200: {"content": {"audio/wav": {}}}},
)
async def preview_organization_voice(
    request: VoicePreviewRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """A sample of any voice id with the organization's voice model (agent
    voice override, test caller pools)."""
    from api.brand.local_models import LocalModelsError, synthesize_preview
    from api.services.configuration.ai_model_configuration import (
        get_organization_ai_model_configuration_v2,
    )

    stored = await get_organization_ai_model_configuration_v2(
        user.selected_organization_id
    )
    pipeline = getattr(getattr(stored, "byok", None), "pipeline", None)
    tts = getattr(pipeline, "tts", None) if pipeline else None
    if tts is None or not getattr(tts, "base_url", None):
        raise HTTPException(status_code=422, detail="No voice model configured")
    keys = tts.get_all_api_keys() if hasattr(tts, "get_all_api_keys") else []
    try:
        audio = await synthesize_preview(
            base_url=tts.base_url,
            api_key=keys[0] if keys else None,
            model=tts.model,
            voice=request.voice,
            speed=request.speed or getattr(tts, "speed", None),
            language=getattr(tts, "language", None),
            text=request.text,
        )
    except LocalModelsError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return Response(content=audio, media_type="audio/wav")


class GenerateRecordingRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    voice: str | None = Field(default=None, max_length=120)
    speed: float | None = Field(default=None, ge=0.5, le=2.0)
    name: str | None = Field(default=None, max_length=64)
    # Also use it as this agent's greeting (draft).
    greeting_workflow_id: int | None = None


class RecordingGreetingRequest(BaseModel):
    workflow_id: int
    # None: back to the agent's text greeting.
    recording_pk: int | None = None


def _greeting_result(saved) -> dict:
    return {
        "workflow_id": saved.workflow_id,
        "draft_definition_id": saved.id,
        "draft_version_number": saved.version_number,
    }


@router.post("/recordings/generate")
async def generate_recording(
    request: GenerateRecordingRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Synthesize a text with the organization's voice model and store it
    as a recording; optionally use it as an agent's greeting (in a draft)."""
    from api.brand import recordings

    org = user.selected_organization_id
    try:
        recording = await recordings.generate(
            org,
            user,
            text=request.text,
            voice=request.voice,
            speed=request.speed,
            name=request.name,
        )
        greeting = None
        if request.greeting_workflow_id is not None:
            saved = await recordings.set_greeting(
                org, user, request.greeting_workflow_id, recording.id
            )
            greeting = _greeting_result(saved)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except recordings.RecordingError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {
        "id": recording.id,
        "recording_id": recording.recording_id,
        "storage_key": recording.storage_key,
        "greeting": greeting,
    }


class RecordingPreviewRequest(BaseModel):
    voice: str | None = Field(default=None, max_length=120)
    speed: float | None = Field(default=None, ge=0.5, le=2.0)
    text: str | None = Field(default=None, max_length=1000)


@router.post(
    "/recordings/preview",
    response_class=Response,
    responses={200: {"content": {"audio/wav": {}}}},
)
async def preview_recording(
    request: RecordingPreviewRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """The start of a recording to generate (organization voice by default)."""
    from api.brand import recordings
    from api.brand.local_models import LocalModelsError, synthesize_preview

    try:
        tts = await recordings.organization_tts(user.selected_organization_id)
        audio = await synthesize_preview(
            base_url=tts.base_url,
            api_key=recordings._api_key(tts),
            model=tts.model,
            voice=(request.voice or "").strip() or tts.voice,
            speed=request.speed or getattr(tts, "speed", None),
            language=getattr(tts, "language", None),
            text=request.text,
            volume_gain_db=getattr(tts, "volume_gain_db", None),
            pronunciations=getattr(tts, "pronunciations", None),
        )
    except recordings.RecordingError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except LocalModelsError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return Response(content=audio, media_type="audio/wav")


@router.get("/recordings/agent-greeting/{workflow_id}")
async def recording_agent_greeting(
    workflow_id: int,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """The agent's greeting text and voice (draft, else published version)."""
    from api.brand import recordings

    try:
        return await recordings.agent_greeting(
            user.selected_organization_id, workflow_id
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except recordings.RecordingError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("/recordings/greeting")
async def recording_greeting(
    request: RecordingGreetingRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Greeting of an agent from a recording, or back to its text (draft)."""
    from api.brand import recordings

    try:
        saved = await recordings.set_greeting(
            user.selected_organization_id,
            user,
            request.workflow_id,
            request.recording_pk,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except recordings.RecordingError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _greeting_result(saved)


class EngineSettingsRequest(BaseModel):
    """Blocks to set; a block set to null goes back to the built-in values."""

    speaking_plan: dict | None = None
    performance: dict | None = None
    audio: dict | None = None


async def _engine_settings_view(organization_id: int) -> dict:
    from api.brand import agent_tuning as tuning

    platform = await tuning.get_engine_settings(organization_id)
    return {
        "builtin": tuning.BUILTIN,
        "platform": {b: platform.get(b) for b in tuning.BLOCKS},
        "effective": {b: tuning.effective_block(b, platform) for b in tuning.BLOCKS},
    }


@router.get("/engine-settings")
async def get_engine_settings(
    user: UserModel = Depends(get_user_with_selected_organization),
):
    """Call-engine settings of the platform: built-in values (what was
    hardcoded), the organization's values, and the effective result. Agents
    override them block by block in their own settings."""
    return await _engine_settings_view(user.selected_organization_id)


@router.put("/engine-settings")
async def save_engine_settings(
    request: EngineSettingsRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
):
    from pydantic import ValidationError

    from api.brand import agent_tuning as tuning

    try:
        await tuning.save_engine_settings(
            user.selected_organization_id, request.model_dump(exclude_unset=True)
        )
    except (ValidationError, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return await _engine_settings_view(user.selected_organization_id)


if BRAND.test_campaigns:
    from api.brand.test_routes import router as tests_router

    router.include_router(tests_router)
