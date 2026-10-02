"""Per-agent tuning: voice override and low-level performance settings.

Both live in the agent's workflow configuration, hence in its versions
(diffs, restore, test-campaign comparisons):

``voice_override``  voice, speed, language, gain of the agent, applied on top of
                    the organization's voice model at run time. Unlike
                    upstream's model override (a full copy of the
                    organization's models), the agent keeps following the
                    organization's endpoint, key and model.

``performance``     knobs that were hardcoded in the call pipeline. Every key
                    is optional: absent means today's behaviour.

    tts_first_chunk_ms      audio received before the first audio frame is
                            played (pipecat waits for 500 ms of audio)
    vad_stop_secs           silence before the voice detector reports the end
                            of speech (0.2 s)
    vad_confidence          speech probability needed to count as voice (0.7)
    vad_min_volume          minimum volume to count as voice (0.6)
    llm_temperature         sampling temperature (local LLMs get none today:
                            the server's default)
    llm_max_tokens          cap on the length of a reply (none today)
    mute_during_tools       the caller cannot interrupt while a tool runs (on)
    mute_until_first_reply  the caller is not heard until the agent's first
                            reply has been spoken (on)
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError

VOICE_KEY = "voice_override"
PERFORMANCE_KEY = "performance"


class VoiceOverride(BaseModel):
    model_config = ConfigDict(extra="ignore")

    voice: str | None = Field(default=None, max_length=120)
    speed: float | None = Field(default=None, ge=0.5, le=2.0)
    language: str | None = Field(default=None, max_length=20)
    volume_gain_db: float | None = Field(default=None, ge=-12, le=12)


class Performance(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tts_first_chunk_ms: int | None = Field(default=None, ge=20, le=500)
    vad_stop_secs: float | None = Field(default=None, ge=0.1, le=1.0)
    vad_confidence: float | None = Field(default=None, ge=0.3, le=0.95)
    vad_min_volume: float | None = Field(default=None, ge=0.05, le=0.9)
    llm_temperature: float | None = Field(default=None, ge=0.0, le=1.5)
    llm_max_tokens: int | None = Field(default=None, ge=16, le=4000)
    mute_during_tools: bool | None = None
    mute_until_first_reply: bool | None = None


def voice_override(configs: dict | None) -> VoiceOverride | None:
    raw = (configs or {}).get(VOICE_KEY)
    if not isinstance(raw, dict):
        return None
    try:
        override = VoiceOverride.model_validate(raw)
    except ValidationError as e:
        logger.warning(f"Invalid voice override, ignored: {e}")
        return None
    return override if override.model_dump(exclude_none=True) else None


def performance(configs: dict | None) -> Performance:
    raw = (configs or {}).get(PERFORMANCE_KEY)
    if not isinstance(raw, dict):
        return Performance()
    try:
        return Performance.model_validate(raw)
    except ValidationError as e:
        logger.warning(f"Invalid performance settings, defaults used: {e}")
        return Performance()


def apply_voice_override(effective: Any, configs: dict | None) -> Any:
    """The effective model configuration with the agent's voice settings."""
    override = voice_override(configs)
    tts = getattr(effective, "tts", None)
    if override is None or tts is None:
        return effective
    fields = getattr(type(tts), "model_fields", {})
    update = {
        k: v for k, v in override.model_dump(exclude_none=True).items() if k in fields
    }
    if update:
        effective.tts = tts.model_copy(update=update)
    return effective


def vad_params(params: Any, configs: dict | None) -> Any:
    """VADParams with the agent's settings (start_secs kept as given)."""
    perf = performance(configs)
    changes = {
        k: v
        for k, v in {
            "stop_secs": perf.vad_stop_secs,
            "confidence": perf.vad_confidence,
            "min_volume": perf.vad_min_volume,
        }.items()
        if v is not None
    }
    return params.model_copy(update=changes) if changes else params


def mute_strategies(strategies: list, configs: dict | None) -> list:
    """The user mute strategies minus the ones the agent turned off."""
    from pipecat.turns.user_mute import (
        FunctionCallUserMuteStrategy,
        MuteUntilFirstBotCompleteUserMuteStrategy,
    )

    perf = performance(configs)
    out = []
    for s in strategies:
        if perf.mute_during_tools is False and isinstance(
            s, FunctionCallUserMuteStrategy
        ):
            continue
        if perf.mute_until_first_reply is False and isinstance(
            s, MuteUntilFirstBotCompleteUserMuteStrategy
        ):
            continue
        out.append(s)
    return out


def tune_services(*, llm: Any, tts: Any, configs: dict | None) -> None:
    """Sampling of the conversation LLM, first audio chunk of the voice."""
    perf = performance(configs)
    settings = getattr(llm, "_settings", None)
    if settings is not None:
        if perf.llm_temperature is not None and hasattr(settings, "temperature"):
            settings.temperature = perf.llm_temperature
        if perf.llm_max_tokens is not None:
            for key in ("max_tokens", "max_completion_tokens"):
                if hasattr(settings, key):
                    setattr(settings, key, perf.llm_max_tokens)
                    break
    applied = perf.model_dump(exclude_none=True)
    tts_settings = getattr(tts, "_settings", None)
    if applied or voice_override(configs):
        logger.info(
            f"Agent tuning: performance {applied}; voice "
            f"{getattr(tts_settings, 'voice', None)} speed {getattr(tts_settings, 'speed', None)}"
        )
    if perf.tts_first_chunk_ms is not None and tts is not None:
        # Read by LocalModelsTTSService.run_tts (the sample rate is only known
        # once the pipeline started).
        tts.oxee_first_chunk_ms = perf.tts_first_chunk_ms
