"""Local Models TTS: the Speaches service plus language, text preparation and gain.

Oxeegen's ``voxee-tts-pro`` accepts ``language`` on ``/v1/audio/speech`` (as
well as ``voice``, ``speed``, ``response_format`` and ``stream``); the pipecat
Speaches service does not send it. The endpoint has no volume or pronunciation
controls, so both are applied here: the text is rewritten before synthesis
(pronunciation dictionary, French normalization; see ``speech_text``) and a
gain is applied to the returned PCM. Transcripts keep the original text since
only the synthesis request is rewritten. Pipecat itself stays untouched.
"""

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

    # Agent setting (api/brand/agent_tuning.py): audio to receive before the
    # first frame is played; None keeps pipecat's chunk (500 ms).
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
                async for chunk in self._audio_chunks(response):
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
        except BadRequestError as e:
            yield ErrorFrame(error=f"Unknown error occurred: {e}")
