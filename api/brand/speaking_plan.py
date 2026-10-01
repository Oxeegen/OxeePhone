"""Speaking plans: when the agent takes the floor and when it yields it.

Vapi-style per-agent settings, stored in the workflow configuration under
``speaking_plan`` and applied by the call pipeline (run_pipeline.py):

Start speaking plan (when the agent answers)
    wait_seconds              floor between the end of the caller's turn and
                              the agent's first audio. Pipeline latency counts
                              towards it: the agent never waits longer than
                              max(wait_seconds, pipeline latency).
    smart_endpointing         "off" -> the three waits below decide the end of
                              the caller's turn from the transcript ending;
                              "smart_turn" -> the Smart Turn model decides.
    on_punctuation_seconds    silence needed after a transcript ending in . ! ?
    on_no_punctuation_seconds silence needed after a transcript without a
                              final punctuation (the caller may go on)
    on_number_seconds         silence needed after a transcript ending in a
                              number (phone numbers, dates are often dictated
                              in chunks)

Stop speaking plan (when the caller interrupts the agent)
    num_words                 words the caller must say, while the agent
                              speaks, to interrupt it; 0 = on voice
    voice_seconds             speech the voice detector needs before it
                              reports the caller speaking
    backoff_seconds           after an interruption, the agent waits at least
                              this long before speaking again
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from api.brand.config import BRAND
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterruptionFrame,
    OutputAudioRawFrame,
    TranscriptionFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.turns.types import ProcessFrameResult
from pipecat.turns.user_start import (
    MinWordsUserTurnStartStrategy,
    TranscriptionUserTurnStartStrategy,
    VADUserTurnStartStrategy,
)
from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy

CONFIG_KEY = "speaking_plan"


class StartSpeakingPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    wait_seconds: float = Field(default=0.4, ge=0, le=5)
    smart_endpointing: Literal["off", "smart_turn"] = "off"
    on_punctuation_seconds: float = Field(default=0.1, ge=0, le=3)
    on_no_punctuation_seconds: float = Field(default=1.5, ge=0, le=3)
    on_number_seconds: float = Field(default=0.5, ge=0, le=3)


class StopSpeakingPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    num_words: int = Field(default=0, ge=0, le=10)
    voice_seconds: float = Field(default=0.2, ge=0, le=0.5)
    backoff_seconds: float = Field(default=1.0, ge=0, le=10)


class SpeakingPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    start: StartSpeakingPlan = Field(default_factory=StartSpeakingPlan)
    stop: StopSpeakingPlan = Field(default_factory=StopSpeakingPlan)


def resolve_speaking_plan(run_configs: dict | None) -> SpeakingPlan | None:
    """The agent's speaking plan, or None to keep the upstream turn settings.

    Agents saved before the speaking plans existed have no ``speaking_plan``
    key and keep behaving exactly as before.
    """
    if not BRAND.speaking_plan or not run_configs:
        return None
    raw = run_configs.get(CONFIG_KEY)
    if not isinstance(raw, dict):
        return None
    try:
        return SpeakingPlan.model_validate(raw)
    except ValidationError as e:
        logger.warning(f"Invalid speaking plan, using the defaults: {e}")
        return SpeakingPlan()


# --- End of the caller's turn -----------------------------------------------

_PUNCTUATION_END = re.compile(r"[.!?…。？！]['\"»”)\]]*$")
_NUMBER_END = re.compile(r"\d[\d\s.,:/h%€-]*$")


def ending_kind(text: str) -> Literal["punctuation", "number", "none"]:
    """How a transcript ends: a number wins over the dot STT puts after it."""
    t = text.strip()
    if not t:
        return "none"
    if _NUMBER_END.search(t.rstrip(".!?… ")):
        return "number"
    if _PUNCTUATION_END.search(t):
        return "punctuation"
    return "none"


class SpeakingPlanUserTurnStopStrategy(SpeechTimeoutUserTurnStopStrategy):
    """Speech timeout whose length depends on how the transcript ends.

    The silence is measured from the moment the caller stopped speaking (the
    VAD stop, minus the silence VAD itself waited). Until the transcript is
    known the shortest wait is armed; when it arrives, the timer is re-armed
    for what is left of the wait matching its ending.
    """

    def __init__(self, plan: StartSpeakingPlan, **kwargs):
        self._plan = plan
        self._silence_started = time.monotonic()
        super().__init__(user_speech_timeout=self._shortest_wait(), **kwargs)

    def _shortest_wait(self) -> float:
        p = self._plan
        return min(p.on_punctuation_seconds, p.on_no_punctuation_seconds, p.on_number_seconds)

    def wait_for(self, text: str) -> float:
        if not text.strip():
            return self._shortest_wait()
        kind = ending_kind(text)
        if kind == "number":
            return self._plan.on_number_seconds
        if kind == "punctuation":
            return self._plan.on_punctuation_seconds
        return self._plan.on_no_punctuation_seconds

    def _remaining(self, text: str) -> float:
        return max(0.0, self.wait_for(text) - (time.monotonic() - self._silence_started))

    async def _handle_vad_user_stopped_speaking(self, frame: VADUserStoppedSpeakingFrame):
        self._silence_started = time.monotonic() - (frame.stop_secs or 0.0)
        await super()._handle_vad_user_stopped_speaking(frame)

    async def _handle_transcription(self, frame: TranscriptionFrame):
        if not self._vad_user_speaking and not self._vad_stopped:
            # Transcript without a VAD stop: the silence starts now.
            self._silence_started = time.monotonic()
        elif not self._vad_user_speaking and self._vad_stopped:
            # The ending is known now: wait what is left of the matching delay.
            text = self._text + frame.text
            remaining = self._remaining(text)
            logger.info(
                f"Speaking plan: {ending_kind(text)} ending, end of turn in {remaining:.2f}s"
            )
            await self._arm_user_speech_timer(remaining)
        await super()._handle_transcription(frame)

    async def _restart_user_speech_timer(self):
        await self._arm_user_speech_timer(self._remaining(self._text))

    async def _arm_user_speech_timer(self, timeout: float):
        if self._user_speech_timeout_task:
            await self.task_manager.cancel_task(self._user_speech_timeout_task)
            self._user_speech_timeout_task = None
        if timeout <= 0:
            self._user_speech_wait_done = True
            return
        self._user_speech_wait_done = False
        self._user_speech_timeout_task = self.task_manager.create_task(
            self._user_speech_timeout_handler(timeout),
            f"{self}::_user_speech_timeout_handler",
        )


# --- Interrupting the agent -------------------------------------------------


class BotSilentVADUserTurnStartStrategy(VADUserTurnStartStrategy):
    """Voice starts the caller's turn only while the agent is silent.

    Paired with the min-words strategy: while the agent speaks, only enough
    words interrupt it.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._bot_speaking = False

    async def process_frame(self, frame: Frame) -> ProcessFrameResult:
        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
        elif isinstance(frame, VADUserStartedSpeakingFrame) and self._bot_speaking:
            return ProcessFrameResult.CONTINUE
        return await super().process_frame(frame)


def user_turn_start_strategies(plan: SpeakingPlan):
    if plan.stop.num_words <= 0:
        return [TranscriptionUserTurnStartStrategy(), VADUserTurnStartStrategy()]
    return [
        BotSilentVADUserTurnStartStrategy(),
        MinWordsUserTurnStartStrategy(min_words=plan.stop.num_words),
    ]


def user_turn_stop_strategies(plan: SpeakingPlan):
    """None when smart endpointing is on: run_pipeline builds upstream's
    Smart Turn analyzer (turn_analyzer strategy, smart_turn_stop_secs)."""
    if plan.start.smart_endpointing == "smart_turn":
        return None
    return [SpeakingPlanUserTurnStopStrategy(plan.start)]


def vad_start_secs(plan: SpeakingPlan) -> float:
    return plan.stop.voice_seconds


def user_turn_stop_timeout(plan: SpeakingPlan, default: float) -> float:
    """Keep the aggregator's safety timeout above the longest configured wait."""
    s = plan.start
    longest = max(s.on_punctuation_seconds, s.on_no_punctuation_seconds, s.on_number_seconds)
    return max(default, longest + 2.0)


# --- When the agent takes the floor -----------------------------------------


class SpeakingPlanGate(FrameProcessor):
    """Holds the agent's first audio of a reply until it may speak.

    Sits right before the output transport. After the caller's turn ends the
    first audio waits until ``wait_seconds`` have passed since that end; after
    the caller interrupted the agent, until ``backoff_seconds`` have passed
    since the interruption. Already-late audio (slow pipeline) passes at once.
    """

    def __init__(self, plan: SpeakingPlan, **kwargs):
        super().__init__(**kwargs)
        self._wait = plan.start.wait_seconds
        self._backoff = plan.stop.backoff_seconds
        self._bot_speaking = False
        self._not_before: float | None = None

    def _hold_until(self, deadline: float):
        self._not_before = max(self._not_before or 0.0, deadline)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
        elif isinstance(frame, InterruptionFrame):
            if self._bot_speaking and self._backoff > 0:
                self._hold_until(time.monotonic() + self._backoff)
        elif isinstance(frame, UserStoppedSpeakingFrame) and direction == FrameDirection.DOWNSTREAM:
            if self._wait > 0:
                self._hold_until(time.monotonic() + self._wait)
        elif isinstance(frame, OutputAudioRawFrame) and self._not_before is not None:
            delay = self._not_before - time.monotonic()
            self._not_before = None
            if delay > 0:
                logger.info(f"Speaking plan: holding the reply {delay:.2f}s")
                await asyncio.sleep(delay)

        await self.push_frame(frame, direction)


def speaking_plan_gate(plan: SpeakingPlan | None) -> list[FrameProcessor]:
    if plan is None or (plan.start.wait_seconds <= 0 and plan.stop.backoff_seconds <= 0):
        return []
    return [SpeakingPlanGate(plan, name="SpeakingPlanGate")]
