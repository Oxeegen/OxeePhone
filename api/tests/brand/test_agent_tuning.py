"""OxeePhone: per-agent voice override and performance settings."""

import pytest
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.turns.user_mute import (
    CallbackUserMuteStrategy,
    FunctionCallUserMuteStrategy,
    MuteUntilFirstBotCompleteUserMuteStrategy,
)

from api.brand import agent_tuning as tuning
from api.brand.version_diff import diff_versions
from api.services.configuration.registry import SpeachesTTSConfiguration


class _Effective:
    def __init__(self):
        self.tts = SpeachesTTSConfiguration(
            model="voxee-tts-pro", voice="fr_cedric", base_url="http://tts/v1", speed=1.0
        )


def test_voice_override_keeps_the_organization_model():
    eff = tuning.apply_voice_override(
        _Effective(), {"voice_override": {"voice": "fr_lea", "speed": 1.15, "nope": 1}}
    )
    assert eff.tts.voice == "fr_lea" and eff.tts.speed == 1.15
    assert eff.tts.model == "voxee-tts-pro" and eff.tts.base_url == "http://tts/v1"
    same = tuning.apply_voice_override(_Effective(), {"voice_override": {}})
    assert same.tts.voice == "fr_cedric"
    bad = tuning.apply_voice_override(_Effective(), {"voice_override": {"speed": 9}})
    assert bad.tts.speed == 1.0  # out of range: ignored


def test_vad_params_keep_start_secs():
    base = VADParams(stop_secs=0.2, start_secs=0.3)
    tuned = tuning.vad_params(base, {"performance": {"vad_stop_secs": 0.35, "vad_confidence": 0.8}})
    assert (tuned.stop_secs, tuned.start_secs, tuned.confidence) == (0.35, 0.3, 0.8)
    assert tuning.vad_params(base, {}) is base


def test_mute_strategies():
    strategies = [
        MuteUntilFirstBotCompleteUserMuteStrategy(),
        FunctionCallUserMuteStrategy(),
        CallbackUserMuteStrategy(should_mute_callback=lambda: False),
    ]
    kept = tuning.mute_strategies(
        strategies, {"performance": {"mute_during_tools": False, "mute_until_first_reply": False}}
    )
    assert [type(s) for s in kept] == [CallbackUserMuteStrategy]
    assert tuning.mute_strategies(strategies, {"performance": {"mute_during_tools": True}}) == strategies


class _Settings:
    temperature = None
    max_tokens = None


class _Service:
    def __init__(self):
        self._settings = _Settings()
        self.sample_rate = 24000


def test_tune_services():
    llm, tts = _Service(), _Service()
    tuning.tune_services(
        llm=llm, tts=tts, configs={"performance": {"llm_temperature": 0.3, "llm_max_tokens": 200, "tts_first_chunk_ms": 60}}
    )
    assert llm._settings.temperature == 0.3 and llm._settings.max_tokens == 200
    assert tts.oxee_first_chunk_ms == 60


@pytest.mark.asyncio
async def test_first_audio_chunk_is_smaller():
    from api.brand.tts import LocalModelsTTSService

    class _Response:
        async def iter_bytes(self, size=None):
            for _ in range(10):
                yield b"\x00" * 1000

    svc = LocalModelsTTSService.__new__(LocalModelsTTSService)
    svc._sample_rate = 24000
    svc.oxee_first_chunk_ms = 50  # 2 400 bytes
    sizes = [len(c) async for c in svc._audio_chunks(_Response())]
    assert sizes[0] == 2400 and sum(sizes) == 10000
    assert all(s <= svc.chunk_size for s in sizes)


def test_performance_switch_off_shows_in_the_diff():
    def version(configs):
        return {"workflow_json": {}, "workflow_configurations": configs, "template_context_variables": {}}

    diff = diff_versions(
        version({}), version({"performance": {"mute_during_tools": False}, "voice_override": {"voice": "fr_lea"}})
    )
    labels = [f["label"] for c in diff["changes"] for f in c["fields"]]
    assert any("mute during tools" in label for label in labels)
    assert any(label.startswith("Voice") for label in labels)
