"""Extra per-call data for the OxeePhone call-detail page.

Persisted as additional ``realtime_feedback_events`` in ``workflow_runs.logs``
(same stamping and ordering as upstream events; the upstream UI ignores
unknown event types):

- ``oxee-recording-started``: when the audio buffer started recording, so
  transcript timestamps can be placed on the recordings.
- ``oxee-latency-breakdown``: pipecat's per-turn ``LatencyBreakdown`` — named
  contributions (transcription, endpointing, LLM, speech synthesis...) that
  sum to the user-to-bot latency, plus service TTFBs and function calls.

Bot transcript events also get ``payload.interrupted = true`` when the user
cut the bot off (see ``transcript_log_coordinator``).
"""

from typing import Any

RECORDING_STARTED = "oxee-recording-started"
LATENCY_BREAKDOWN = "oxee-latency-breakdown"


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


async def mark_recording_started(logs_buffer: Any) -> None:
    """Append the recording-start marker; never raises (runs on call connect)."""
    from loguru import logger

    try:
        await logs_buffer.append({"type": RECORDING_STARTED, "payload": {}})
    except Exception as e:
        logger.warning(f"Could not record the recording start marker: {e}")
