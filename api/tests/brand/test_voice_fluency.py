"""OxeePhone: voice fluency (generation speed, gaps heard by the caller)."""

import pytest

from api.brand import tts as brand_tts
from api.brand.call_insights import voice_summary
from api.brand.test_technical import technical_report


class _Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_gaps_are_counted_when_audio_runs_out(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(brand_tts.time, "monotonic", clock)
    stats = brand_tts.VoiceStats(16000)  # 32 000 bytes per second
    clock.now = 100.25
    stats.chunk(8000)  # first audio at 250 ms: 0.25 s of speech
    clock.now = 100.45
    stats.chunk(16000)  # 0.2 s later, still 0.05 s of audio left
    clock.now = 101.40
    stats.chunk(16000)  # 0.75 s of audio played by 101.0: 0.4 s gap
    clock.now = 101.50
    stats.chunk(16000)  # on the shifted schedule: in time
    clock.now = 101.6
    payload = stats.payload(context_id="c1", chars=40)
    assert payload["first_audio_ms"] == 250
    assert payload["gaps"] == 1 and payload["gap_ms"] == 400
    assert payload["audio_ms"] == 1750 and payload["synthesis_ms"] == 1600
    assert payload["speed"] == pytest.approx(1.09, abs=0.01)


def test_voice_summary_groups_sentences_by_reply():
    summary = voice_summary(
        [
            {"context_id": "a", "synthesis_ms": 400, "audio_ms": 1600, "speed": 4.0, "gaps": 0, "gap_ms": 0},
            {"context_id": "a", "synthesis_ms": 600, "audio_ms": 1200, "speed": 2.0, "gaps": 1, "gap_ms": 120},
            {"context_id": "b", "synthesis_ms": 500, "audio_ms": 2000, "speed": 4.0, "gaps": 0, "gap_ms": 0},
            {"context_id": "c", "audio_ms": 0},
        ]
    )
    assert summary["sentences"] == 3 and summary["replies"] == 2
    assert summary["speed"] == pytest.approx(3.2)
    assert summary["speed_min"] == 2.0 and summary["replies_with_gaps"] == 1
    assert summary["reply_synthesis_ms"] == [500, 1000]
    assert voice_summary([]) is None


def _call(index, voice):
    return {
        "index": index,
        "scenario": {"title": f"s{index}"},
        "status": "done",
        "metrics": {
            "latency": {"turn_stages": [{"total": 900, "perceived": 1100, "stages": {"endpointing": 200}}]},
            "voice": voice,
            "tools": [],
            "agent_turns": 2,
            "interruptions": 0,
            "errors": 0,
            "models": {},
        },
    }


def _voice(audio, synthesis, replies=4, with_gaps=0):
    return {
        "sentences": replies * 2, "replies": replies, "synthesis_ms": synthesis, "audio_ms": audio,
        "speed": audio / synthesis, "speed_min": 1.2, "gaps": with_gaps, "gap_ms": 90 * with_gaps,
        "replies_with_gaps": with_gaps, "reply_synthesis_ms": [synthesis / replies] * replies,
    }


def test_voice_fluency_post():
    from api.brand.analysis_thresholds import DEFAULTS

    fast = technical_report([_call(1, _voice(12000, 4000))], DEFAULTS)
    post = next(p for p in fast["posts"] if p["key"] == "voice_fluency")
    assert post["p50"] == 3.0 and post["score"] == 5
    slow = technical_report([_call(1, _voice(5000, 4000)), _call(2, _voice(5000, 4000, with_gaps=1))], DEFAULTS)
    post = next(p for p in slow["posts"] if p["key"] == "voice_fluency")
    assert post["p50"] == 1.25 and post["score"] == 2  # under ×1.5, gaps in 1 of 8 replies
    none = technical_report([_call(1, None)], DEFAULTS)
    assert "voice_fluency" not in {p["key"] for p in none["posts"]}
