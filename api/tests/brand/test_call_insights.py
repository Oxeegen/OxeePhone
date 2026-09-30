"""OxeePhone lot 4: extra per-call data for the call-detail page."""

import dataclasses

from pipecat.observers.user_bot_latency_observer import (
    LatencyBreakdown,
    LatencyContribution,
    LatencyOwnerKind,
    MeasuredFrom,
    TTFBBreakdownMetrics,
)

from api.brand import BRAND
from api.brand.call_insights import LATENCY_BREAKDOWN, build_latency_breakdown_event
from api.services.pipecat import transcript_log_coordinator
from api.services.pipecat.in_memory_buffers import InMemoryLogsBuffer


def test_latency_breakdown_event_is_json_ready():
    breakdown = LatencyBreakdown(
        contributions=[
            LatencyContribution(
                key="transcription",
                label="transcription",
                owner="STT#0",
                owner_kind=LatencyOwnerKind.SERVICE,
                start_time=10.0,
                duration_secs=0.3,
            ),
            LatencyContribution(
                key="llm_inference",
                label="LLM inference",
                owner="LLM#0",
                owner_kind=LatencyOwnerKind.SERVICE,
                start_time=10.3,
                duration_secs=0.7,
            ),
        ],
        ttfb=[
            TTFBBreakdownMetrics(
                processor="LLM#0",
                model="Oxee-flash",
                start_time=10.3,
                duration_secs=0.7,
            )
        ],
        measured_from=MeasuredFrom.USER_SILENCE,
        total_secs=1.0,
        user_turn_secs=0.3,
    )
    event = build_latency_breakdown_event(breakdown)
    assert event["type"] == LATENCY_BREAKDOWN
    payload = event["payload"]
    assert payload["total_secs"] == 1.0
    assert payload["measured_from"] == "user_silence"
    assert [c["key"] for c in payload["contributions"]] == [
        "transcription",
        "llm_inference",
    ]
    assert payload["contributions"][0]["owner_kind"] == "service"
    assert payload["ttfb"][0]["model"] == "Oxee-flash"


async def _bot_event(monkeypatch, *, call_insights: bool, interrupted: bool):
    monkeypatch.setattr(
        transcript_log_coordinator,
        "BRAND",
        dataclasses.replace(BRAND, call_insights=call_insights),
    )
    buffer = InMemoryLogsBuffer(workflow_run_id=1)
    coordinator = transcript_log_coordinator.TranscriptLogCoordinator(buffer)
    await coordinator.record_turn_started(1)
    await coordinator.record_assistant_transcript(
        text="Bonjour, je vous écoute", timestamp=None
    )
    await coordinator.record_turn_ended(1, interrupted=interrupted)
    await coordinator.flush()
    return next(e for e in buffer.get_events() if e["type"] == "rtf-bot-text")


async def test_interrupted_bot_message_is_flagged(monkeypatch):
    event = await _bot_event(monkeypatch, call_insights=True, interrupted=True)
    assert event["payload"]["interrupted"] is True


async def test_no_flag_when_not_interrupted_or_disabled(monkeypatch):
    assert (
        "interrupted"
        not in (await _bot_event(monkeypatch, call_insights=True, interrupted=False))[
            "payload"
        ]
    )
    assert (
        "interrupted"
        not in (await _bot_event(monkeypatch, call_insights=False, interrupted=True))[
            "payload"
        ]
    )


async def test_recording_marker_is_best_effort():
    from types import SimpleNamespace

    from api.brand.call_insights import RECORDING_STARTED, mark_recording_started

    buffer = InMemoryLogsBuffer(workflow_run_id=1)
    await mark_recording_started(buffer)
    assert buffer.get_events()[0]["type"] == RECORDING_STARTED
    assert buffer.get_events()[0]["timestamp"]

    async def broken(*_a, **_k):
        raise RuntimeError("boom")

    await mark_recording_started(SimpleNamespace(append=broken))  # no raise
    await mark_recording_started(SimpleNamespace())  # no append at all
