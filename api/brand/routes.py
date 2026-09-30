"""OxeePhone API routes, mounted under /api/v1/oxee."""

from datetime import datetime
from typing import Literal

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from pydantic import BaseModel, Field

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
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from api.brand.analysis import (
        MAX_REPORTS,
        REPORT_PREFIX,
        _store_report,
        new_report,
        run_analysis,
    )
    from api.brand.db import delete_configuration, list_configurations_by_prefix

    if request.days not in (1, 7, 30):
        raise HTTPException(status_code=422, detail="days must be 1, 7 or 30")
    try:
        ZoneInfo(request.timezone)
        datetime.strptime(request.date, "%Y-%m-%d")
    except (ValueError, ZoneInfoNotFoundError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    organization_id = user.selected_organization_id
    existing = await list_configurations_by_prefix(
        organization_id, REPORT_PREFIX, limit=200
    )
    for old in existing[MAX_REPORTS - 1 :]:
        await delete_configuration(organization_id, REPORT_PREFIX + old["id"])
    report = new_report(
        date=request.date,
        days=request.days,
        timezone=request.timezone,
        workflow_id=request.workflow_id,
        created_by=str(user.provider_id),
    )
    await _store_report(organization_id, report)
    background_tasks.add_task(
        run_analysis,
        report["id"],
        organization_id=organization_id,
        date=request.date,
        days=request.days,
        timezone=request.timezone,
        workflow_id=request.workflow_id,
        language=request.language,
    )
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
