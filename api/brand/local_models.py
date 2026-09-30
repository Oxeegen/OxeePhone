"""OxeePhone model configuration: BYOK pipeline on self-hosted Local Models.

Every service (LLM, TTS, STT, embeddings) uses the OpenAI-compatible
``speaches`` provider: a base URL, an optional API key and a model picked from
the endpoint's ``GET /models``. The Dograh-managed mode, speech-to-speech
(realtime) and third-party providers are not offered.
"""

from typing import Any

import httpx
from loguru import logger

from api.brand import BRAND
from api.services.configuration.masking import MASK_MARKER, is_mask_of
from api.services.configuration.registry import ServiceProviders, ServiceType
from api.utils.url_security import validate_user_configured_service_url

LOCAL_PROVIDER = ServiceProviders.SPEACHES.value
LOCAL_PROVIDER_TITLE = "Local Models"
PIPELINE_SERVICES = ("llm", "tts", "stt", "embeddings")
MODELS_TIMEOUT = httpx.Timeout(10.0)

# Upstream Speaches defaults point at localhost Ollama/Kokoro; start blank so the
# user fills in the Oxeegen endpoint. STT language defaults to French.
_BLANK_DEFAULTS = ("model", "base_url")
_DEFAULT_OVERRIDES = {
    ServiceType.STT: {"language": "fr"},
    ServiceType.TTS: {"language": "fr", "voice": "fr_cedric"},
}
# Speed range offered in the UI (the endpoint accepts 0.25-4.0).
_TTS_SPEED_RANGE = (0.5, 2.0)


def restrict_provider_schemas(
    service_type: ServiceType, schemas: dict[str, dict]
) -> dict[str, dict]:
    """Keep only the Local Models provider, with neutral defaults."""
    if service_type == ServiceType.REALTIME:
        return {}
    schema = schemas.get(LOCAL_PROVIDER)
    if schema is None:
        return {}
    schema = {**schema, "title": LOCAL_PROVIDER_TITLE}
    schema.pop("provider_docs_url", None)
    properties = {name: dict(prop) for name, prop in schema["properties"].items()}
    for name in _BLANK_DEFAULTS:
        if name in properties:
            properties[name]["default"] = ""
            properties[name].pop("examples", None)
    for name, value in _DEFAULT_OVERRIDES.get(service_type, {}).items():
        if name in properties:
            properties[name]["default"] = value
    if service_type == ServiceType.TTS and "speed" in properties:
        properties["speed"]["minimum"], properties["speed"]["maximum"] = (
            _TTS_SPEED_RANGE
        )
        properties["speed"]["description"] = "Speech speed (0.5 to 2.0)."
    schema["properties"] = properties
    return {LOCAL_PROVIDER: schema}


def default_providers() -> dict[str, str]:
    return {service: LOCAL_PROVIDER for service in PIPELINE_SERVICES}


def enforce_local_models(configuration: Any) -> None:
    """Reject anything but a BYOK pipeline on Local Models.

    Raises ValueError with the validator's ``[{"model", "message"}]`` payload.
    """
    errors: list[dict[str, str]] = []
    byok = getattr(configuration, "byok", None)
    if getattr(configuration, "mode", None) != "byok" or byok is None:
        errors.append(
            {"model": "all", "message": "Only BYOK configurations are allowed."}
        )
    elif byok.mode != "pipeline" or byok.pipeline is None:
        errors.append(
            {"model": "all", "message": "Speech-to-speech (realtime) is not available."}
        )
    else:
        for service in PIPELINE_SERVICES:
            service_config = getattr(byok.pipeline, service, None)
            if service_config is None:
                continue
            if getattr(service_config, "provider", None) != LOCAL_PROVIDER:
                errors.append(
                    {
                        "model": service,
                        "message": f"Only {LOCAL_PROVIDER_TITLE} can be used.",
                    }
                )
    if errors:
        raise ValueError(errors)


def _stored_api_keys(configuration: Any, service: str) -> list[str]:
    pipeline = getattr(getattr(configuration, "byok", None), "pipeline", None)
    service_config = getattr(pipeline, service, None) if pipeline else None
    if service_config is None:
        return []
    return service_config.get_all_api_keys()


def resolve_api_key(
    api_key: str | None, stored_configuration: Any, service: str
) -> str | None:
    """Swap a masked key (as shown in the UI) for the stored one it masks."""
    if not api_key or MASK_MARKER not in api_key:
        return api_key or None
    for real_key in _stored_api_keys(stored_configuration, service):
        if real_key and is_mask_of(api_key, real_key):
            return real_key
    return None


class LocalModelsError(Exception):
    """User-facing error when calling a Local Models endpoint."""


async def list_endpoint_models(base_url: str, api_key: str | None) -> list[str]:
    """Return the model ids served by an OpenAI-compatible endpoint."""
    base_url = (base_url or "").strip().rstrip("/")
    if not base_url:
        raise LocalModelsError("Enter the endpoint base URL first.")
    try:
        validate_user_configured_service_url(base_url, field_name="base_url")
    except ValueError as e:
        raise LocalModelsError(str(e)) from e

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = f"{base_url}/models"
    try:
        async with httpx.AsyncClient(timeout=MODELS_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as e:
        logger.info("Model listing failed for {}: {}", url, e)
        raise LocalModelsError(f"Could not reach {url} ({type(e).__name__}).") from e

    if response.status_code in (401, 403):
        raise LocalModelsError("The endpoint rejected the API key.")
    if response.status_code >= 400:
        raise LocalModelsError(f"{url} answered HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as e:
        raise LocalModelsError(f"{url} did not return JSON.") from e

    items = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise LocalModelsError(f"Unexpected response from {url}.")
    ids = {
        item.get("id") if isinstance(item, dict) else item
        for item in items
        if isinstance(item, (dict, str))
    }
    return sorted(
        model_id for model_id in ids if isinstance(model_id, str) and model_id
    )


def is_enabled() -> bool:
    return BRAND.local_models_only


TRANSCRIPTION_TIMEOUT = httpx.Timeout(120.0)


async def transcribe_with_organization_stt(
    *,
    organization_id: int,
    audio_data: bytes,
    filename: str,
    content_type: str,
    language: str | None,
) -> dict:
    """Transcribe an uploaded recording with the organization's Local Models STT.

    Replaces Dograh's hosted transcription; returns ``{"transcript": str}`` like
    the upstream MPS route.
    """
    from api.services.configuration.ai_model_configuration import (
        get_resolved_ai_model_configuration,
    )

    resolved = await get_resolved_ai_model_configuration(
        organization_id=organization_id
    )
    stt = resolved.effective.stt
    if stt is None or getattr(stt, "provider", None) != LOCAL_PROVIDER:
        raise LocalModelsError(
            "Configure a Transcriber in Models before transcribing recordings."
        )
    base_url = (getattr(stt, "base_url", "") or "").rstrip("/")
    try:
        validate_user_configured_service_url(base_url, field_name="base_url")
    except ValueError as e:
        raise LocalModelsError(str(e)) from e

    api_keys = stt.get_all_api_keys()
    headers = {"Authorization": f"Bearer {api_keys[0]}"} if api_keys else {}
    data = {"model": stt.model, "response_format": "json"}
    if language:
        data["language"] = language
    url = f"{base_url}/audio/transcriptions"
    try:
        async with httpx.AsyncClient(timeout=TRANSCRIPTION_TIMEOUT) as client:
            response = await client.post(
                url,
                headers=headers,
                data=data,
                files={"file": (filename, audio_data, content_type)},
            )
    except httpx.HTTPError as e:
        raise LocalModelsError(f"Could not reach {url} ({type(e).__name__}).") from e
    if response.status_code >= 400:
        raise LocalModelsError(f"{url} answered HTTP {response.status_code}.")
    return {"transcript": (response.json().get("text") or "").strip()}


PREVIEW_TEXT = "Bonjour, je suis votre assistant vocal. Comment puis-je vous aider ?"
PREVIEW_MAX_CHARS = 300


async def synthesize_preview(
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    voice: str,
    speed: float | None,
    language: str | None,
    text: str | None,
) -> bytes:
    """Render a short MP3 sample with the given voice settings (Listen button)."""
    base_url = (base_url or "").strip().rstrip("/")
    if not base_url or not model or not voice:
        raise LocalModelsError("Fill in the base URL, model and voice first.")
    try:
        validate_user_configured_service_url(base_url, field_name="base_url")
    except ValueError as e:
        raise LocalModelsError(str(e)) from e

    body = {
        "model": model,
        "voice": voice,
        "input": (text or PREVIEW_TEXT).strip()[:PREVIEW_MAX_CHARS],
        "response_format": "mp3",
    }
    if speed:
        body["speed"] = speed
    if language:
        body["language"] = language
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = f"{base_url}/audio/speech"
    try:
        async with httpx.AsyncClient(timeout=TRANSCRIPTION_TIMEOUT) as client:
            response = await client.post(url, headers=headers, json=body)
    except httpx.HTTPError as e:
        raise LocalModelsError(f"Could not reach {url} ({type(e).__name__}).") from e
    if response.status_code in (401, 403):
        raise LocalModelsError("The endpoint rejected the API key.")
    if response.status_code >= 400:
        detail = ""
        try:
            detail = response.json().get("detail") or ""
        except ValueError:
            pass
        raise LocalModelsError(
            f"{url} answered HTTP {response.status_code}"
            + (f": {detail}" if isinstance(detail, str) and detail else ".")
        )
    return response.content
