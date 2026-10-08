"""Extra per-call data for the OxeePhone call-detail page.

Persisted as additional ``realtime_feedback_events`` in ``workflow_runs.logs``
(same stamping and ordering as upstream events; the upstream UI ignores
unknown event types):

- ``oxee-recording-started``: when the audio buffer started recording, so
  transcript timestamps can be placed on the recordings.
- ``oxee-latency-breakdown``: pipecat's per-turn ``LatencyBreakdown`` — named
  contributions (transcription, endpointing, LLM, speech synthesis...) that
  sum to the user-to-bot latency, plus service TTFBs and function calls.
- ``oxee-voice-stats``: each sentence synthesized by the Local Models voice:
  time to first audio, total synthesis time, audio length, generation speed
  (audio seconds per second of synthesis) and gaps heard by the caller (see
  ``api/brand/tts.py`` ``VoiceStats``).

Bot transcript events also get ``payload.interrupted = true`` when the user
cut the bot off (see ``transcript_log_coordinator``).
"""

from typing import Any

RECORDING_STARTED = "oxee-recording-started"
LATENCY_BREAKDOWN = "oxee-latency-breakdown"
VOICE_STATS = "oxee-voice-stats"


def build_latency_breakdown_event(breakdown: Any) -> dict:
    data = breakdown.model_dump(mode="json")
    return {
        "type": LATENCY_BREAKDOWN,
        "payload": {
            "total_secs": data.get("total_secs"),
            "measured_from": data.get("measured_from"),
            "user_turn_secs": data.get("user_turn_secs"),
            "contributions": [
                {
                    "key": c.get("key"),
                    "label": c.get("label"),
                    "owner": c.get("owner"),
                    "owner_kind": c.get("owner_kind"),
                    "start_time": c.get("start_time"),
                    "duration_secs": c.get("duration_secs"),
                }
                for c in data.get("contributions") or []
            ],
            "ttfb": data.get("ttfb") or [],
            "function_calls": data.get("function_calls") or [],
            # Sentence aggregation before the first TTS request (LLM streaming
            # until the first speakable sentence).
            "text_aggregation": data.get("text_aggregation"),
        },
    }


class LatencyBreakdownFilter:
    """Drops breakdowns anchored on the call start that are not the greeting.

    pipecat anchors a turn on the caller's VAD stop, and an interruption
    clears that anchor. When the interruption comes after the caller stopped
    (min-words interruptions with a segmented STT), the reply is measured from
    the call start instead: tens of seconds of fake latency.
    """

    def __init__(self):
        self._greeting_seen = False

    def keep(self, breakdown: Any) -> bool:
        # MeasuredFrom is a StrEnum.
        if getattr(breakdown, "measured_from", None) != "client_connected":
            return True
        if self._greeting_seen:
            return False
        self._greeting_seen = True
        return True


def voice_summary(payloads: list[dict]) -> dict | None:
    """Voice fluency of a call from its ``oxee-voice-stats`` events.

    Replies group the sentences of one context (one agent reply)."""
    sentences = [p for p in payloads if isinstance(p, dict) and p.get("audio_ms")]
    if not sentences:
        return None
    replies: dict[str, dict] = {}
    for p in sentences:
        r = replies.setdefault(
            str(p.get("context_id")), {"synthesis_ms": 0, "audio_ms": 0, "gaps": 0}
        )
        r["synthesis_ms"] += p.get("synthesis_ms") or 0
        r["audio_ms"] += p.get("audio_ms") or 0
        r["gaps"] += p.get("gaps") or 0
    synthesis = sum(p.get("synthesis_ms") or 0 for p in sentences)
    audio = sum(p.get("audio_ms") or 0 for p in sentences)
    return {
        "sentences": len(sentences),
        "synthesis_ms": synthesis,
        "audio_ms": audio,
        "replies": len(replies),
        "speed": round(audio / synthesis, 2) if synthesis else None,
        "speed_min": min(
            (p["speed"] for p in sentences if p.get("speed") is not None), default=None
        ),
        "gaps": sum(p.get("gaps") or 0 for p in sentences),
        "gap_ms": sum(p.get("gap_ms") or 0 for p in sentences),
        "replies_with_gaps": sum(1 for r in replies.values() if r["gaps"]),
        "reply_synthesis_ms": sorted(r["synthesis_ms"] for r in replies.values()),
    }


async def mark_recording_started(logs_buffer: Any) -> None:
    """Append the recording-start marker; never raises (runs on call connect)."""
    from loguru import logger

    try:
        await logs_buffer.append({"type": RECORDING_STARTED, "payload": {}})
    except Exception as e:
        logger.warning(f"Could not record the recording start marker: {e}")
