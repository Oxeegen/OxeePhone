"""OxeePhone API routes, mounted under /api/v1/oxee."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
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
    service: Literal["llm", "tts", "stt", "embeddings"]
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
