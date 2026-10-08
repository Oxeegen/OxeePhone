"""Technical quality of test calls: a 1-5 score per post and overall.

Each post (reply time, greeting, end-of-turn detection, transcriber, LLM,
voice, tools, turn-taking, reliability) is measured on the agent side of the
calls and graded against the organization's analysis thresholds (Analysis ›
Thresholds), the same ones the configuration analysis uses:

    value ≤ ½ threshold → 5 · ≤ ¾ → 4 · ≤ threshold → 3 · ≤ critical → 2 · above → 1

The critical level is the post's own critical threshold when there is one
(reply time), 1.5 × the threshold otherwise. A post whose p90 is above the
critical level loses one point (a slow tail is heard). The overall score is
the weighted mean of the posts measured. Text executions have no timing:
only tools and reliability are graded.
"""

from __future__ import annotations

from typing import Any

POSTS: list[dict[str, Any]] = [
    {
        "key": "reply",
        "label": "Reply time",
        "help": "From the end of the caller's turn to the agent's first audio. The end-of-turn wait is a setting of the agent: shown apart, not counted.",
        "threshold": "reply_p50_warn_ms",
        "critical": "reply_p50_crit_ms",
        "unit": "ms",
        "weight": 3,
        "phone": True,
    },
    {
        "key": "greeting",
        "label": "Greeting",
        "help": "From the call connecting to the agent's first audio.",
        "threshold": "greeting_warn_ms",
        "unit": "ms",
        "weight": 1,
        "phone": True,
    },
    {
        "key": "transcriber",
        "label": "Transcriber",
        "help": "Speech-to-text, to the final transcript of the caller's turn.",
        "threshold": "transcriber_stage_warn_ms",
        "unit": "ms",
        "weight": 1,
        "stage": True,
        "model": "stt_model",
        "phone": True,
    },
    {
        "key": "llm",
        "label": "LLM",
        "help": "From the request to the first sentence ready to be spoken (first token + streaming).",
        "threshold": "llm_stage_warn_ms",
        "unit": "ms",
        "weight": 2,
        "stage": True,
        "model": "llm_model",
        "phone": True,
    },
    {
        "key": "voice",
        "label": "Voice",
        "help": "Text-to-speech, to the first audio.",
        "threshold": "voice_stage_warn_ms",
        "unit": "ms",
        "weight": 1,
        "stage": True,
        "model": "tts_model",
        "phone": True,
    },
    {
        "key": "voice_fluency",
        "label": "Voice fluency",
        "help": "Seconds of speech generated per second of synthesis (×1 = just in time) and gaps heard inside the agent's sentences. The voice delay above only covers the first audio.",
        "threshold": "voice_speed_warn",
        "critical": "voice_speed_crit",
        "unit": "x",
        "weight": 1,
        "phone": True,
    },
    {
        "key": "tools",
        "label": "Tools",
        "help": "Duration and failures of the agent's tool calls.",
        "threshold": "tool_slow_ms",
        "unit": "ms",
        "weight": 1,
    },
    {
        "key": "turn_taking",
        "label": "Turn-taking",
        "help": "Share of the agent's replies cut off by the caller.",
        "threshold": "interruption_rate_warn",
        "unit": "rate",
        "weight": 1,
        "phone": True,
    },
    {
        "key": "reliability",
        "label": "Reliability",
        "help": "Calls that failed to play or had a pipeline error.",
        "unit": "rate",
        "weight": 2,
    },
]
# Stages shown for information (no score): their share of the reply time.
# The end-of-turn wait is not part of it: its share is of the perceived time.
INFO_STAGES = {
    "endpointing": "End-of-turn wait (setting, not counted)",
    "sentence": "First sentence",
    "transport": "Transport",
    "tools": "Tools (in replies)",
    "other": "Other",
}
RELIABILITY_WARN = 0.05


def _percentile(values: list[float], pct: float) -> float | None:
    from api.brand.insights import _percentile as percentile

    return percentile([v for v in values if v is not None], pct)


def upgrade_latency(metrics: dict | None) -> dict | None:
    """Latency of a call measured before the reply time excluded the
    end-of-turn wait: same shape as ``call_metrics`` now (idempotent)."""
    latency = (metrics or {}).get("latency")
    turns = (latency or {}).get("turn_stages")
    if not turns or all("perceived" in t for t in turns):
        return metrics
    for t in turns:
        if "perceived" not in t:
            t["perceived"] = t["total"]
            t["total"] = max(0, t["total"] - (t["stages"].get("endpointing") or 0))
    totals = [t["total"] for t in turns]
    latency.update(
        values_ms=totals,
        p50_ms=_percentile(totals, 0.5),
        p90_ms=_percentile(totals, 0.9),
        perceived_p50_ms=_percentile([t["perceived"] for t in turns], 0.5),
    )
    return metrics


def grade(
    value: float | None, warn: float, critical: float | None = None
) -> int | None:
    if value is None or not warn:
        return None
    critical = critical or warn * 1.5
    if value <= warn * 0.5:
        return 5
    if value <= warn * 0.75:
        return 4
    if value <= warn:
        return 3
    if value <= critical:
        return 2
    return 1


def status(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 4:
        return "good"
    if score >= 3:
        return "fair"
    if score >= 2:
        return "warning"
    return "critical"


def _post(spec: dict, values: list[float], th: dict, extra: dict | None = None) -> dict:
    warn = th.get(spec.get("threshold")) if spec.get("threshold") else None
    critical = th.get(spec.get("critical")) if spec.get("critical") else None
    p50, p90 = _percentile(values, 0.5), _percentile(values, 0.9)
    score = grade(p50, warn, critical) if warn else None
    crit_level = critical or (warn * 1.5 if warn else None)
    if score and p90 is not None and crit_level and p90 > crit_level:
        score = max(1, score - 1)
    return {
        "key": spec["key"],
        "label": spec["label"],
        "help": spec["help"],
        "unit": spec["unit"],
        "weight": spec["weight"],
        "samples": len(values),
        "p50": round(p50, 3) if p50 is not None else None,
        "p90": round(p90, 3) if p90 is not None else None,
        "max": round(max(values), 3) if values else None,
        "threshold": warn,
        "critical": crit_level,
        "over_rate": (
            round(sum(1 for v in values if v > warn) / len(values), 4)
            if values and warn
            else None
        ),
        "score": score,
        "status": status(score),
        **(extra or {}),
    }


def grade_speed(speed: float | None, warn: float, critical: float) -> int | None:
    """Higher is better: ×2 the warning level and more is 5."""
    if speed is None or not warn:
        return None
    if speed >= warn * 2:
        return 5
    if speed >= warn * 1.5:
        return 4
    if speed >= warn:
        return 3
    if speed >= critical:
        return 2
    return 1


GAP_REPLIES_WARN = 0.05


def voice_fluency_post(spec: dict, metrics: list[dict], th: dict) -> dict | None:
    voices = [m["voice"] for m in metrics if m.get("voice")]
    if not voices:
        return None
    synthesis = sum(v["synthesis_ms"] for v in voices)
    speed = round(sum(v["audio_ms"] for v in voices) / synthesis, 2) if synthesis else None
    replies = sum(v["replies"] for v in voices)
    with_gaps = sum(v["replies_with_gaps"] for v in voices)
    gap_rate = with_gaps / replies if replies else 0.0
    warn = th.get("voice_speed_warn", 1.5)
    critical = th.get("voice_speed_crit", 1.1)
    score = grade_speed(speed, warn, critical)
    if score is not None and with_gaps:
        score = min(score, 2 if gap_rate > GAP_REPLIES_WARN else 3)
    synth = sorted(ms for v in voices for ms in v["reply_synthesis_ms"])
    return {
        "key": spec["key"],
        "label": spec["label"],
        "help": spec["help"],
        "unit": spec["unit"],
        "weight": spec["weight"],
        "samples": replies,
        "p50": speed,
        "p90": None,
        "max": None,
        "threshold": warn,
        "critical": critical,
        "over_rate": round(gap_rate, 4),
        "score": score,
        "status": status(score),
        "speed_min": min((v["speed_min"] for v in voices if v["speed_min"] is not None), default=None),
        "gaps": sum(v["gaps"] for v in voices),
        "gap_ms": sum(v["gap_ms"] for v in voices),
        "replies_with_gaps": with_gaps,
        "reply_synthesis_p50_ms": _percentile(synth, 0.5),
        "reply_synthesis_p90_ms": _percentile(synth, 0.9),
    }


def _models(metrics: list[dict], key: str) -> str | None:
    seen = [
        m.get("models", {}).get(key) for m in metrics if m.get("models", {}).get(key)
    ]
    return max(set(seen), key=seen.count) if seen else None


def technical_report(
    calls: list[dict], thresholds: dict, *, channel: str = "phone"
) -> dict:
    """Posts and overall score of a set of test calls (an execution)."""
    played = [c for c in calls if c.get("status") in ("done", "error")]
    metrics = [upgrade_latency(c["metrics"]) for c in played if c.get("metrics")]
    turns = [t for m in metrics for t in (m["latency"].get("turn_stages") or [])]
    posts = []
    for spec in POSTS:
        if spec.get("phone") and channel != "phone":
            continue
        key = spec["key"]
        if key == "reply":
            values = [t["total"] for t in turns]
        elif key == "greeting":
            values = [
                m["latency"]["greeting_ms"]
                for m in metrics
                if m["latency"].get("greeting_ms")
            ]
        elif spec.get("stage"):
            values = [t["stages"].get(key, 0) for t in turns]
        elif key == "tools":
            tools = [t for m in metrics for t in m["tools"]]
            values = [t["ms"] for t in tools if t["ms"] is not None]
            failure = (
                (sum(1 for t in tools if t["failed"]) / len(tools)) if tools else None
            )
            post = _post(
                spec, values, thresholds, {"calls": len(tools), "failure_rate": failure}
            )
            failure_score = grade(failure, thresholds.get("tool_error_rate_warn", 0.1))
            if failure_score is not None and failure:
                post["score"] = min(post["score"] or 5, failure_score)
                post["status"] = status(post["score"])
            if tools:
                posts.append(post)
            continue
        elif key == "voice_fluency":
            post = voice_fluency_post(spec, metrics, thresholds)
            if post:
                posts.append(post)
            continue
        elif key == "turn_taking":
            agent = sum(m["agent_turns"] for m in metrics)
            rate = (sum(m["interruptions"] for m in metrics) / agent) if agent else None
            post = _post(
                spec,
                [],
                thresholds,
                {"interruptions": sum(m["interruptions"] for m in metrics)},
            )
            post.update(p50=round(rate, 4) if rate is not None else None, samples=agent)
            post["score"] = grade(rate, thresholds.get("interruption_rate_warn", 0.25))
            post["status"] = status(post["score"])
            if agent:
                posts.append(post)
            continue
        elif key == "reliability":
            failed = sum(
                1
                for c in played
                if c.get("status") == "error" or (c.get("metrics") or {}).get("errors")
            )
            rate = failed / len(played) if played else None
            post = _post(spec, [], thresholds, {"failed_calls": failed})
            post.update(
                p50=round(rate, 4) if rate is not None else None,
                samples=len(played),
                threshold=RELIABILITY_WARN,
            )
            post["score"] = grade(rate, RELIABILITY_WARN, RELIABILITY_WARN * 3)
            post["status"] = status(post["score"])
            if played:
                posts.append(post)
            continue
        else:
            values = []
        if not values:
            continue
        extra = {"model": _models(metrics, spec["model"])} if spec.get("model") else {}
        posts.append(_post(spec, values, thresholds, extra))

    reply_p50 = _percentile([t["total"] for t in turns], 0.5)
    perceived_p50 = _percentile([t.get("perceived", t["total"]) for t in turns], 0.5)
    for p in posts:  # share of the reply time, for the stages
        if p["key"] in ("transcriber", "llm", "voice") and reply_p50:
            p["share"] = round((p["p50"] or 0) / reply_p50, 4)
    info = []
    if turns and reply_p50:
        for stage, label in INFO_STAGES.items():
            p50 = _percentile([t["stages"].get(stage, 0) for t in turns], 0.5)
            counted = stage != "endpointing"
            base = reply_p50 if counted else perceived_p50
            info.append(
                {
                    "key": stage,
                    "label": label,
                    "p50": p50,
                    "share": round((p50 or 0) / base, 4) if base else None,
                    "counted": counted,
                }
            )
    scored = [p for p in posts if p["score"] is not None]
    score = (
        round(
            sum(p["score"] * p["weight"] for p in scored)
            / sum(p["weight"] for p in scored),
            2,
        )
        if scored
        else None
    )
    worst = sorted(
        (
            {
                "index": c["index"],
                "title": c["scenario"].get("title"),
                "score": c["technical"]["score"],
                "weakest": c["technical"].get("weakest"),
            }
            for c in played
            if (c.get("technical") or {}).get("score") is not None
        ),
        key=lambda x: x["score"],
    )[:5]
    return {
        "score": score,
        "status": status(score),
        "channel": channel,
        "replies": len(turns),
        "perceived_p50": perceived_p50,
        "posts": posts,
        "info_stages": info,
        "worst_calls": worst,
        "thresholds": {
            k: v for k, v in thresholds.items() if k.endswith(("_ms", "_rate_warn"))
        },
    }


def call_technical(call: dict, thresholds: dict, *, channel: str) -> dict:
    """The same grading on one call (shown on each call of the report)."""
    played = {**call, "status": "error" if call.get("status") == "error" else "done"}
    report = technical_report([played], thresholds, channel=channel)
    scored = [p for p in report["posts"] if p["score"] is not None]
    weakest = min(scored, key=lambda p: p["score"]) if scored else None
    return {
        "score": report["score"],
        "status": report["status"],
        "posts": {p["key"]: p["score"] for p in report["posts"]},
        "weakest": weakest["label"] if weakest and weakest["score"] < 4 else None,
    }
