"""OxeePhone: platform call-engine settings, agent overrides, sampling."""

from types import SimpleNamespace

import pytest

from api.brand import agent_tuning as tuning
from api.brand import test_runs as runs
from api.services.pipecat.audio_config import create_audio_config


@pytest.fixture
def engine_store(monkeypatch):
    from api.db import db_client

    data = {}

    async def get_configuration(org, key):
        value = data.get((org, key))
        return SimpleNamespace(value=value) if value is not None else None

    async def upsert_configuration(org, key, value):
        data[(org, key)] = value

    monkeypatch.setattr(db_client, "get_configuration", get_configuration)
    monkeypatch.setattr(db_client, "upsert_configuration", upsert_configuration)
    tuning._cache.clear()
    return data


@pytest.mark.asyncio
async def test_platform_blocks_save_and_reset(engine_store):
    saved = await tuning.save_engine_settings(
        5, {"performance": {"vad_stop_secs": 0.3, "llm_temperature": None}, "audio": {"output_packet_ms": 20}, "nope": {}}
    )
    assert saved == {"performance": {"vad_stop_secs": 0.3}, "audio": {"output_packet_ms": 20}}
    assert (await tuning.get_engine_settings(5))["audio"] == {"output_packet_ms": 20}
    saved = await tuning.save_engine_settings(5, {"audio": None})
    assert "audio" not in saved
    with pytest.raises(Exception):
        await tuning.save_engine_settings(5, {"audio": {"webrtc_sample_rate": 44100}})


@pytest.mark.asyncio
async def test_agent_override_wins_block_by_block(engine_store):
    await tuning.save_engine_settings(
        5,
        {
            "performance": {"vad_stop_secs": 0.3},
            "audio": {"output_packet_ms": 20},
            "speaking_plan": {"start": {"wait_seconds": 0.2}, "smart_turn_stop_secs": 3},
        },
    )
    # The agent overrides performance only.
    configs = await tuning.effective_configs(5, {"performance": {"vad_stop_secs": 0.5}})
    assert configs["performance"] == {"vad_stop_secs": 0.5}
    mixed = await tuning.effective_configs(5, {"audio": {"end_silence_secs": 1}})
    assert mixed["audio"] == {"output_packet_ms": 20, "end_silence_secs": 1}
    assert configs["audio"] == {"output_packet_ms": 20}
    assert configs["speaking_plan"]["start"]["wait_seconds"] == 0.2
    assert configs["smart_turn_stop_secs"] == 3
    assert configs["turn_stop_strategy"] == "transcription"
    # An agent with its own plan keeps it.
    own = await tuning.effective_configs(5, {"speaking_plan": {"start": {"wait_seconds": 1.0}}})
    assert own["speaking_plan"]["start"]["wait_seconds"] == 1.0
    # No platform values: nothing injected (built-in behaviour).
    assert await tuning.effective_configs(6, {"x": 1}) == {"x": 1}


def test_effective_block_layers():
    platform = {"performance": {"vad_stop_secs": 0.3}}
    eff = tuning.effective_block("performance", platform, {"performance": {"vad_confidence": 0.8}})
    assert eff["vad_stop_secs"] == 0.3 and eff["vad_confidence"] == 0.8
    assert eff["tts_first_chunk_ms"] == tuning.BUILTIN["performance"]["tts_first_chunk_ms"]


def test_audio_config_and_transport():
    from api.enums import WorkflowRunMode

    webrtc = create_audio_config(WorkflowRunMode.SMALLWEBRTC.value)
    tuned = tuning.audio_config(webrtc, {"audio": {"webrtc_sample_rate": 8000, "recording_buffer_seconds": 2}}, webrtc=True)
    assert (tuned.transport_in_sample_rate, tuned.vad_sample_rate, tuned.pipeline_sample_rate) == (8000, 8000, 8000)
    assert tuned.buffer_size_seconds == 2
    same = tuning.audio_config(create_audio_config("ari"), {"audio": {"webrtc_sample_rate": 16000}}, webrtc=False)
    assert same.pipeline_sample_rate == 8000  # telephony keeps its wire rate

    transport = SimpleNamespace(_params=SimpleNamespace(audio_out_10ms_chunks=4, audio_out_end_silence_secs=2))
    tuning.tune_transport(transport, {"audio": {"output_packet_ms": 20, "end_silence_secs": 0.5}})
    assert transport._params.audio_out_10ms_chunks == 2 and transport._params.audio_out_end_silence_secs == 0.5


def test_engine_changes_between_executions():
    changes = runs.engine_changes({"performance": {"vad_stop_secs": 0.3}}, {})
    assert changes == [{"block": "performance", "key": "vad_stop_secs", "a": 0.3, "b": 0.2}]
    assert runs.engine_changes({}, {}) == []
