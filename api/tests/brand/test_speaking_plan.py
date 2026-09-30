"""OxeePhone: per-agent start / stop speaking plans."""

import asyncio
import time

import pytest
from pipecat.clocks.system_clock import SystemClock
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    InterruptionFrame,
    STTMetadataFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameProcessorSetup
from pipecat.tests.utils import run_test
from pipecat.turns.types import ProcessFrameResult
from pipecat.turns.user_start import (
    MinWordsUserTurnStartStrategy,
    TranscriptionUserTurnStartStrategy,
    VADUserTurnStartStrategy,
)
from pipecat.utils.asyncio.task_manager import TaskManager

from api.brand import speaking_plan as sp


def test_no_plan_keeps_upstream_settings():
    assert sp.resolve_speaking_plan(None) is None
    assert sp.resolve_speaking_plan({"turn_stop_strategy": "transcription"}) is None


def test_plan_defaults_and_invalid_values():
    plan = sp.resolve_speaking_plan({"speaking_plan": {"start": {"wait_seconds": 0.8}}})
    assert plan.start.wait_seconds == 0.8
    assert plan.start.on_no_punctuation_seconds == 1.5
    assert plan.stop.num_words == 0
    # Out of range: the whole plan falls back to the defaults, never crashes a call.
    bad = sp.resolve_speaking_plan({"speaking_plan": {"stop": {"num_words": 50}}})
    assert bad == sp.SpeakingPlan()


@pytest.mark.parametrize(
    "text,kind",
    [
        ("Bonjour, je voudrais un rendez-vous.", "punctuation"),
        ("C'est urgent !", "punctuation"),
        ("Vous êtes ouverts ?", "punctuation"),
        ("je voudrais un rendez-vous", "none"),
        ("Mon numéro c'est le 06 12 34", "number"),
        ("Mon numéro c'est le 06 12 34.", "number"),
        ("demain à 14h", "number"),
        ("   ", "none"),
    ],
)
def test_ending_kind(text, kind):
    assert sp.ending_kind(text) == kind


def _plan(**start):
    return sp.StartSpeakingPlan(
        on_punctuation_seconds=start.get("punct", 0.1),
        on_no_punctuation_seconds=start.get("no_punct", 0.6),
        on_number_seconds=start.get("number", 0.3),
    )


async def _strategy(plan):
    strategy = sp.SpeakingPlanUserTurnStopStrategy(plan)
    await strategy.setup(
        FrameProcessorSetup(clock=SystemClock(), task_manager=TaskManager(), pipeline_worker=None)
    )
    await strategy.process_frame(STTMetadataFrame(service_name="t", ttfs_p99_latency=0.0))
    stopped = []

    @strategy.event_handler("on_user_turn_stopped")
    async def on_stopped(_strategy, _params):
        stopped.append(time.monotonic())

    return strategy, stopped


async def _say(strategy, text):
    await strategy.process_frame(VADUserStartedSpeakingFrame())
    await strategy.process_frame(VADUserStoppedSpeakingFrame(stop_secs=0.0))
    t0 = time.monotonic()
    await strategy.process_frame(
        TranscriptionFrame(text=text, user_id="u", timestamp="", finalized=True)
    )
    return t0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,expected",
    [("Oui, c'est ça.", 0.1), ("oui mais alors", 0.6), ("au 06 12 34", 0.3)],
)
async def test_wait_depends_on_transcript_ending(text, expected):
    strategy, stopped = await _strategy(_plan())
    t0 = await _say(strategy, text)
    await asyncio.sleep(0.9)
    assert len(stopped) == 1
    assert stopped[0] - t0 == pytest.approx(expected, abs=0.08)
    await strategy.cleanup()


@pytest.mark.asyncio
async def test_speaking_again_cancels_the_wait():
    strategy, stopped = await _strategy(_plan())
    await _say(strategy, "je voudrais")
    await asyncio.sleep(0.2)
    await strategy.process_frame(VADUserStartedSpeakingFrame())
    await asyncio.sleep(0.6)
    assert stopped == []
    await strategy.cleanup()


@pytest.mark.asyncio
async def test_transcript_late_after_silence_triggers_at_once():
    strategy, stopped = await _strategy(_plan())
    await strategy.process_frame(VADUserStartedSpeakingFrame())
    await strategy.process_frame(VADUserStoppedSpeakingFrame(stop_secs=0.0))
    await asyncio.sleep(0.3)  # slow STT: punctuation wait (0.1 s) already over
    t0 = time.monotonic()
    await strategy.process_frame(
        TranscriptionFrame(text="Merci.", user_id="u", timestamp="", finalized=True)
    )
    await asyncio.sleep(0.05)
    assert len(stopped) == 1 and stopped[0] - t0 < 0.03
    await strategy.cleanup()


def test_start_strategies():
    on_voice = sp.user_turn_start_strategies(sp.SpeakingPlan())
    assert [type(s) for s in on_voice] == [
        TranscriptionUserTurnStartStrategy,
        VADUserTurnStartStrategy,
    ]
    words = sp.user_turn_start_strategies(sp.SpeakingPlan(stop=sp.StopSpeakingPlan(num_words=3)))
    assert [type(s) for s in words] == [
        sp.BotSilentVADUserTurnStartStrategy,
        MinWordsUserTurnStartStrategy,
    ]
    smart = sp.SpeakingPlan(start=sp.StartSpeakingPlan(smart_endpointing="smart_turn"))
    assert sp.user_turn_stop_strategies(smart) is None


@pytest.mark.asyncio
async def test_voice_does_not_interrupt_while_the_agent_speaks():
    strategy = sp.BotSilentVADUserTurnStartStrategy()
    await strategy.setup(FrameProcessorSetup(clock=SystemClock(), task_manager=TaskManager(), pipeline_worker=None))
    started = []

    @strategy.event_handler("on_user_turn_started")
    async def on_started(_strategy, _params):
        started.append(True)

    await strategy.process_frame(BotStartedSpeakingFrame())
    assert await strategy.process_frame(VADUserStartedSpeakingFrame()) == ProcessFrameResult.CONTINUE
    assert started == []


def _audio():
    return TTSAudioRawFrame(audio=b"\x00\x00" * 160, sample_rate=16000, num_channels=1)


@pytest.mark.asyncio
async def test_gate_waits_after_the_turn_ends():
    plan = sp.SpeakingPlan(start=sp.StartSpeakingPlan(wait_seconds=0.4))
    t0 = time.monotonic()
    await run_test(
        sp.SpeakingPlanGate(plan),
        frames_to_send=[UserStoppedSpeakingFrame(), _audio()],
        expected_down_frames=[UserStoppedSpeakingFrame, TTSAudioRawFrame],
    )
    assert time.monotonic() - t0 >= 0.4


@pytest.mark.asyncio
async def test_gate_backs_off_after_an_interruption():
    plan = sp.SpeakingPlan(
        start=sp.StartSpeakingPlan(wait_seconds=0), stop=sp.StopSpeakingPlan(backoff_seconds=0.5)
    )
    gate = sp.SpeakingPlanGate(plan)
    gate._bot_speaking = True
    t0 = time.monotonic()
    await run_test(
        gate,
        frames_to_send=[InterruptionFrame(), _audio()],
        expected_down_frames=[InterruptionFrame, TTSAudioRawFrame],
    )
    assert time.monotonic() - t0 >= 0.5


@pytest.mark.asyncio
async def test_gate_lets_late_audio_through():
    plan = sp.SpeakingPlan(start=sp.StartSpeakingPlan(wait_seconds=0.4))
    gate = sp.SpeakingPlanGate(plan)
    t0 = time.monotonic()
    await run_test(gate, frames_to_send=[_audio()], expected_down_frames=[TTSAudioRawFrame])
    assert time.monotonic() - t0 < 0.3


def test_no_gate_when_nothing_to_wait():
    assert sp.speaking_plan_gate(None) == []
    nothing = sp.SpeakingPlan(
        start=sp.StartSpeakingPlan(wait_seconds=0), stop=sp.StopSpeakingPlan(backoff_seconds=0)
    )
    assert sp.speaking_plan_gate(nothing) == []
