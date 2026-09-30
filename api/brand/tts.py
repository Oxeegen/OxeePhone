"""Local Models TTS: the Speaches service plus a language hint.

Oxeegen's ``voxee-tts-pro`` accepts ``language`` on ``/v1/audio/speech`` (as
well as ``voice``, ``speed``, ``response_format`` and ``stream``); the pipecat
Speaches service does not send it. The only change from
``SpeachesTTSService.run_tts`` is the extra ``language`` body field, so pipecat
itself stays untouched.
"""

from loguru import logger
from openai import BadRequestError
from pipecat.frames.frames import ErrorFrame, TTSAudioRawFrame
from pipecat.services.speaches.tts import SpeachesTTSService
from pipecat.utils.tracing.service_decorators import traced_tts


class LocalModelsTTSService(SpeachesTTSService):
    def __init__(self, *, language: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._language_hint = (language or "").strip() or None

    def speech_params(self, text: str) -> dict:
        params = {
            "input": text,
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

                async for chunk in response.iter_bytes(self.chunk_size):
                    if len(chunk) > 0:
                        await self.stop_ttfb_metrics()
                        yield TTSAudioRawFrame(
                            chunk,
                            self.sample_rate,
                            1,
                            context_id=context_id,
                        )
        except BadRequestError as e:
            yield ErrorFrame(error=f"Unknown error occurred: {e}")
