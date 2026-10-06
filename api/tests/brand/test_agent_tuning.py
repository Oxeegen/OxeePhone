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


def test_first_audio_chunk_defaults_to_250_ms():
    tts = _Service()
    tuning.tune_services(llm=_Service(), tts=tts, configs={})
    assert tts.oxee_first_chunk_ms == 250
    assert tuning.BUILTIN["performance"]["tts_first_chunk_ms"] == 250


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


async def _pieces(aggregator, tokens):
    out = []
    for token in tokens:
        out += [a.text async for a in aggregator.aggregate(token)]
    rest = await aggregator.flush()
    return out + ([rest.text] if rest else [])


@pytest.mark.asyncio
async def test_first_clause_goes_before_the_sentence_ends():
    from api.brand.text_aggregation import FirstClauseAggregator

    agg = FirstClauseAggregator()
    pieces = await _pieces(agg, ["D'accord Monsieur Martin,", " je regarde", " votre dossier. Un instant,", " s'il vous plaît."])
    assert pieces == ["D'accord Monsieur Martin,", "je regarde votre dossier.", "Un instant, s'il vous plaît."]
    # Next reply: the first clause is armed again (flush resets).
    pieces = await _pieces(agg, ["Oui, c'est noté.", " Merci,", " au revoir."])
    assert pieces[0] == "Oui, c'est noté."  # "Oui," is too short


@pytest.mark.asyncio
async def test_first_clause_ignores_numbers():
    from api.brand.text_aggregation import FirstClauseAggregator

    pieces = await _pieces(FirstClauseAggregator(), ["Le rendez-vous est à 10:30 pour 3,5 heures. Ensuite, rien."])
    assert pieces[0] == "Le rendez-vous est à 10:30 pour 3,5 heures."


def test_first_clause_setting_swaps_the_aggregator():
    from pipecat.utils.text.simple_text_aggregator import SimpleTextAggregator

    from api.brand.text_aggregation import FirstClauseAggregator

    tts = _Service()
    tts._text_aggregator = SimpleTextAggregator()
    tuning.tune_services(llm=_Service(), tts=tts, configs={"performance": {"tts_first_clause": True}})
    assert isinstance(tts._text_aggregator, FirstClauseAggregator)
    other = _Service()
    other._text_aggregator = SimpleTextAggregator()
    tuning.tune_services(llm=_Service(), tts=other, configs={})
    assert type(other._text_aggregator) is SimpleTextAggregator
