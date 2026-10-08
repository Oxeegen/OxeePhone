"""Local Models TTS: the Speaches service plus language, text preparation and gain.

Oxeegen's ``voxee-tts-pro`` accepts ``language`` on ``/v1/audio/speech`` (as
well as ``voice``, ``speed``, ``response_format`` and ``stream``); the pipecat
Speaches service does not send it. The endpoint has no volume or pronunciation
controls, so both are applied here: the text is rewritten before synthesis
(pronunciation dictionary, French normalization; see ``speech_text``) and a
gain is applied to the returned PCM. Transcripts keep the original text since
only the synthesis request is rewritten. Pipecat itself stays untouched.
"""

import time
from collections.abc import Awaitable, Callable

import numpy as np
from loguru import logger
from openai import BadRequestError
from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame
from pipecat.services.speaches.tts import SpeachesTTSService
from pipecat.utils.tracing.service_decorators import traced_tts

from api.brand.speech_text import parse_pronunciations, prepare_speech_text


def gain_factor(volume_gain_db: float | None) -> float:
    return 10 ** ((volume_gain_db or 0.0) / 20)


def apply_gain(pcm: bytes, factor: float) -> bytes:
    """Scale 16-bit little-endian PCM, clipping instead of wrapping around."""
    if factor == 1.0 or not pcm:
        return pcm
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) * factor
    return np.clip(samples, -32768, 32767).astype("<i2").tobytes()


# A chunk arriving this late after the audio already received has been played
# out means the caller heard a gap.
GAP_TOLERANCE_SECS = 0.05


class VoiceStats:
    """Synthesis of one sentence, as the caller experiences it.

    Playback starts with the first chunk and runs at real time; a later chunk
    that arrives after the audio received so far has been played out is a gap
    (the voice model generated slower than it is spoken).
    """

    def __init__(self, sample_rate: int):
        self._bytes_per_sec = sample_rate * 2  # 16-bit mono PCM
        self._started = time.monotonic()
        self._first: float | None = None  # first audio received
        self._playback: float | None = None  # playback start, shifted by gaps
        self._bytes = 0
        self.gaps = 0
        self.gap_secs = 0.0

    def chunk(self, size: int) -> None:
        if not size:
            return
        now = time.monotonic()
        if self._first is None:
            self._first = self._playback = now
        else:
            late = (now - self._playback) - self._bytes / self._bytes_per_sec
            if late > GAP_TOLERANCE_SECS:
                self.gaps += 1
                self.gap_secs += late
                # Playback resumes with this chunk: later chunks are timed
                # against the shifted schedule.
                self._playback += late
        self._bytes += size

    def payload(self, **extra) -> dict:
        end = time.monotonic()
        audio_secs = self._bytes / self._bytes_per_sec
        synthesis_secs = end - self._started
        return {
            **extra,
            "first_audio_ms": round((self._first - self._started) * 1000)
            if self._first is not None
            else None,
            "synthesis_ms": round(synthesis_secs * 1000),
            "audio_ms": round(audio_secs * 1000),
            "speed": round(audio_secs / synthesis_secs, 2) if synthesis_secs > 0 else None,
            "gaps": self.gaps,
            "gap_ms": round(self.gap_secs * 1000),
        }


class LocalModelsTTSService(SpeachesTTSService):
    def __init__(
        self,
        *,
        language: str | None = None,
        volume_gain_db: float | None = None,
        pronunciations: str | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._language_hint = (language or "").strip() or None
        self._gain = gain_factor(volume_gain_db)
        self._pronunciations = parse_pronunciations(pronunciations)

    def speech_text(self, text: str) -> str:
        return prepare_speech_text(
            text, language=self._language_hint, pronunciations=self._pronunciations
        )

    def speech_params(self, text: str) -> dict:
        params = {
            "input": self.speech_text(text),
            "model": self._settings.model,
            "voice": self._settings.voice,
            "response_format": "pcm",
        }
        if self._settings.speed:
            params["speed"] = self._settings.speed
        extra_body = {"language": self._language_hint} if self._language_hint else None
        if extra_body:
            params["extra_body"] = extra_body
        return params

    # Call-engine setting (api/brand/agent_tuning.py, 250 ms by default): audio
    # to receive before the first frame is played; None keeps pipecat's chunk
    # (500 ms).
    oxee_first_chunk_ms: int | None = None

    async def _audio_chunks(self, response):
        """The response audio: a first, smaller chunk when the agent asks for
        it, then pipecat's usual chunk size."""
        if not self.oxee_first_chunk_ms:
            async for chunk in response.iter_bytes(self.chunk_size):
                yield chunk
            return
        rate = self.sample_rate or 24000
        first = max(2, int(rate * self.oxee_first_chunk_ms / 1000) * 2)
        buffer, sent_first = b"", False
        async for piece in response.iter_bytes():
            buffer += piece
            limit = self.chunk_size if sent_first else first
            while len(buffer) >= limit:
                yield buffer[:limit]
                buffer = buffer[limit:]
                sent_first = True
                limit = self.chunk_size
        if buffer:
            yield buffer

    # Call insights (api/brand/call_insights.py): called with the voice
    # statistics of each synthesized sentence.
    oxee_on_voice_stats: Callable[[dict], Awaitable[None]] | None = None

    @traced_tts
    async def run_tts(self, text: str, context_id: str):
        try:
            async with self._client.audio.speech.with_streaming_response.create(
                **self.speech_params(text)
            ) as response:
                if response.status_code != 200:
                    error = await response.text()
                    logger.error(
                        f"{self} error getting audio (status: {response.status_code}, error: {error})"
                    )
                    yield ErrorFrame(
                        error=f"Error getting audio (status: {response.status_code}, error: {error})"
                    )
                    return

                await self.start_tts_usage_metrics(text)

                # Gain works on whole 16-bit samples: carry an odd trailing byte.
                carry = b""
                stats = VoiceStats(self.sample_rate or 24000)
                async for chunk in self._audio_chunks(response):
                    stats.chunk(len(chunk))
                    if len(chunk) > 0:
                        await self.stop_ttfb_metrics()
                        data = carry + chunk
                        cut = len(data) - (len(data) % 2)
                        carry = data[cut:]
                        if not cut:
                            continue
                        yield TTSAudioRawFrame(
                            apply_gain(data[:cut], self._gain),
                            self.sample_rate,
                            1,
                            context_id=context_id,
                        )
                if self.oxee_on_voice_stats is not None:
                    try:
                        await self.oxee_on_voice_stats(
                            stats.payload(context_id=context_id, chars=len(text))
                        )
                    except Exception as e:
                        logger.debug(f"Voice statistics not recorded: {e}")
        except BadRequestError as e:
            yield ErrorFrame(error=f"Unknown error occurred: {e}")
