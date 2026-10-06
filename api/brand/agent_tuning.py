"""Call-engine settings: platform values and per-agent overrides.

Three blocks (speaking plan, performance, audio & sampling) have
built-in values (``BUILTIN``: what was hardcoded in the pipeline), platform
values set in Platform Settings (organization configuration
``OXEE_ENGINE_SETTINGS``, not versioned) and optional per-agent overrides in the
agent's workflow configuration (versioned with the agent). A speaking plan an
agent overrides is used whole; for performance and audio, the fields the agent
sets win and the others come from the platform, then the built-in behaviour. The agent's voice overrides the organization's
voice model (Models › Voice) the same way.

Agent keys (workflow configuration, hence in the versions, diffs, restore and
test-campaign comparisons):

``voice_override``  voice, speed, language, gain of the agent, applied on top of
                    the organization's voice model at run time. Unlike
                    upstream's model override (a full copy of the
                    organization's models), the agent keeps following the
                    organization's endpoint, key and model.

``performance``     knobs that were hardcoded in the call pipeline. Every key
                    is optional: absent means today's behaviour.

    tts_first_chunk_ms      audio received before the first audio frame is
                            played (250 ms by default; pipecat alone waits for
                            500 ms of audio, which voxee-tts-pro does not need:
                            its first audio comes after ~250 ms)
    tts_first_clause        the first piece of a reply goes to the voice model
                            at its first comma, without waiting for the end of
                            the sentence (off)
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

import copy
import time
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError

VOICE_KEY = "voice_override"
PERFORMANCE_KEY = "performance"
AUDIO_KEY = "audio"
SPEAKING_PLAN_KEY = "speaking_plan"
SMART_TURN_KEY = "smart_turn_stop_secs"
ENGINE_KEY = "OXEE_ENGINE_SETTINGS"
BLOCKS = (SPEAKING_PLAN_KEY, PERFORMANCE_KEY, AUDIO_KEY)


class VoiceOverride(BaseModel):
    model_config = ConfigDict(extra="ignore")

    voice: str | None = Field(default=None, max_length=120)
    speed: float | None = Field(default=None, ge=0.5, le=2.0)
    language: str | None = Field(default=None, max_length=20)
    volume_gain_db: float | None = Field(default=None, ge=-12, le=12)


class Performance(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tts_first_chunk_ms: int | None = Field(default=None, ge=20, le=500)
    tts_first_clause: bool | None = None
    vad_stop_secs: float | None = Field(default=None, ge=0.1, le=1.0)
    vad_confidence: float | None = Field(default=None, ge=0.3, le=0.95)
    vad_min_volume: float | None = Field(default=None, ge=0.05, le=0.9)
    llm_temperature: float | None = Field(default=None, ge=0.0, le=1.5)
    llm_max_tokens: int | None = Field(default=None, ge=16, le=4000)
    mute_during_tools: bool | None = None
    mute_until_first_reply: bool | None = None


class Audio(BaseModel):
    """Audio & sampling (api/services/pipecat/audio_config.py, transports).

    Telephony runs at the operator's wire rate (8 kHz for every provider but
    Vonage, 16 kHz): only the browser (WebRTC) rate can be chosen.
    """

    model_config = ConfigDict(extra="ignore")

    webrtc_sample_rate: Literal[8000, 16000] | None = None
    recording_buffer_seconds: float | None = Field(default=None, ge=1, le=30)
    output_packet_ms: int | None = Field(default=None, ge=10, le=100)
    end_silence_secs: float | None = Field(default=None, ge=0, le=3)


def _builtin() -> dict:
    from api.brand.speaking_plan import SpeakingPlan

    return {
        SPEAKING_PLAN_KEY: {**SpeakingPlan().model_dump(), SMART_TURN_KEY: 2.0},
        PERFORMANCE_KEY: {
            "tts_first_chunk_ms": 250,  # pipecat: 500
            "tts_first_clause": False,
            "vad_stop_secs": 0.2,
            "vad_confidence": 0.7,
            "vad_min_volume": 0.6,
            "llm_temperature": None,  # the model server's default
            "llm_max_tokens": None,  # no limit
            "mute_during_tools": True,
            "mute_until_first_reply": True,
        },
        AUDIO_KEY: {
            "webrtc_sample_rate": 16000,
            "recording_buffer_seconds": 5.0,
            "output_packet_ms": 40,
            "end_silence_secs": 2.0,
        },
    }


# Values hardcoded in the pipeline before these settings existed (except the
# first audio chunk, lowered to 250 ms after measuring voxee-tts-pro).
BUILTIN = _builtin()


def _validate_block(block: str, value: Any) -> dict | None:
    """A clean block (unset fields dropped) or None."""
    from api.brand.speaking_plan import SpeakingPlan

    if not isinstance(value, dict) or not value:
        return None
    if block == SPEAKING_PLAN_KEY:
        plan = SpeakingPlan.model_validate(value).model_dump()
        smart = value.get(SMART_TURN_KEY)
        if smart is not None:
            plan[SMART_TURN_KEY] = max(0.5, min(10.0, float(smart)))
        return plan
    model = {PERFORMANCE_KEY: Performance, AUDIO_KEY: Audio}[block]
    return model.model_validate(value).model_dump(exclude_none=True) or None


_cache: dict[int, tuple[float, dict]] = {}
CACHE_SECONDS = 30.0


async def get_engine_settings(organization_id: int | None) -> dict:
    """The platform blocks of an organization ({block: values}, unset absent)."""
    from api.db import db_client

    if organization_id is None:
        return {}
    hit = _cache.get(organization_id)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return copy.deepcopy(hit[1])
    row = await db_client.get_configuration(organization_id, ENGINE_KEY)
    raw = dict(row.value) if row and row.value else {}
    settings = {}
    for block in BLOCKS:
        try:
            clean = _validate_block(block, raw.get(block))
        except (ValidationError, TypeError, ValueError) as e:
            logger.warning(f"Invalid platform {block} settings ignored: {e}")
            clean = None
        if clean:
            settings[block] = clean
    _cache[organization_id] = (time.monotonic(), settings)
    return copy.deepcopy(settings)


async def save_engine_settings(organization_id: int, changes: dict) -> dict:
    """Set ({block: values}) or reset to the built-in values ({block: None})."""
    from api.db import db_client

    settings = await get_engine_settings(organization_id)
    for block, value in changes.items():
        if block not in BLOCKS:
            continue
        clean = _validate_block(block, value) if value is not None else None
        if clean:
            settings[block] = clean
        else:
            settings.pop(block, None)
    await db_client.upsert_configuration(organization_id, ENGINE_KEY, settings)
    _cache.pop(organization_id, None)
    return settings


def effective_block(block: str, platform: dict, configs: dict | None = None) -> dict:
    """Built-in values, then the platform's, then the agent's override."""
    out = copy.deepcopy(BUILTIN[block])
    out.update(platform.get(block) or {})
    agent = (configs or {}).get(block)
    if isinstance(agent, dict) and agent:
        out.update(agent)
        if block == SPEAKING_PLAN_KEY and (configs or {}).get(SMART_TURN_KEY):
            out[SMART_TURN_KEY] = configs[SMART_TURN_KEY]
    return out


def agent_overrides(configs: dict | None, block: str) -> bool:
    value = (configs or {}).get(block)
    return isinstance(value, dict) and bool(value)


async def effective_configs(organization_id: int | None, configs: dict | None) -> dict:
    """The run's configuration with the platform blocks the agent does not
    override (the pipeline then reads one place)."""
    from api.brand.fixes import _speaking_plan_config

    configs = copy.deepcopy(configs or {})
    platform = await get_engine_settings(organization_id)
    plan = platform.get(SPEAKING_PLAN_KEY)
    if plan and not agent_overrides(configs, SPEAKING_PLAN_KEY):
        plan = dict(plan)
        smart = plan.pop(SMART_TURN_KEY, None)
        configs.update(_speaking_plan_config(plan))
        if smart is not None:
            configs[SMART_TURN_KEY] = smart
    # Fields the agent leaves unset come from the platform.
    for block in (PERFORMANCE_KEY, AUDIO_KEY):
        own = configs.get(block) if agent_overrides(configs, block) else {}
        merged = {**(platform.get(block) or {}), **(own or {})}
        if merged:
            configs[block] = merged
    return configs


def audio(configs: dict | None) -> Audio:
    raw = (configs or {}).get(AUDIO_KEY)
    try:
        return Audio.model_validate(raw) if isinstance(raw, dict) else Audio()
    except ValidationError as e:
        logger.warning(f"Invalid audio settings, defaults used: {e}")
        return Audio()


def audio_config(config: Any, configs: dict | None, *, webrtc: bool) -> Any:
    """The AudioConfig with the agent's sampling settings."""
    from api.services.pipecat.audio_config import AudioConfig

    settings = audio(configs)
    if webrtc and settings.webrtc_sample_rate:
        rate = settings.webrtc_sample_rate
        config = AudioConfig(
            transport_in_sample_rate=rate,
            transport_out_sample_rate=rate,
            vad_sample_rate=rate,
            pipeline_sample_rate=rate,
            buffer_size_seconds=config.buffer_size_seconds,
        )
    if settings.recording_buffer_seconds:
        config.buffer_size_seconds = settings.recording_buffer_seconds
    return config


def tune_transport(transport: Any, configs: dict | None) -> None:
    """Output packet size and end-of-call silence (read when the output starts)."""
    settings = audio(configs)
    params = getattr(transport, "_params", None)
    if params is None:
        return
    if settings.output_packet_ms:
        params.audio_out_10ms_chunks = max(1, round(settings.output_packet_ms / 10))
    if settings.end_silence_secs is not None:
        params.audio_out_end_silence_secs = settings.end_silence_secs


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
    """Sampling of the conversation LLM, first audio chunk and first clause
    of the voice."""
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
    if tts is not None:
        # Read by LocalModelsTTSService.run_tts (the sample rate is only known
        # once the pipeline started).
        tts.oxee_first_chunk_ms = (
            perf.tts_first_chunk_ms or BUILTIN[PERFORMANCE_KEY]["tts_first_chunk_ms"]
        )
        if perf.tts_first_clause:
            from api.brand.text_aggregation import use_first_clause

            use_first_clause(tts)
