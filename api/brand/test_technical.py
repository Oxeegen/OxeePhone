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
        "help": "From the caller falling silent to the agent's first audio.",
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
        "key": "endpointing",
        "label": "End-of-turn detection",
        "help": "Deciding the caller has finished (silence + turn detection, speaking plan).",
        "threshold": "endpointing_stage_warn_ms",
        "unit": "ms",
        "weight": 1,
        "stage": True,
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
# Stages shown for information (no threshold): their share of the reply time.
INFO_STAGES = {
    "sentence": "First sentence",
    "transport": "Transport",
    "tools": "Tools (in replies)",
    "other": "Other",
}
RELIABILITY_WARN = 0.05


def _percentile(values: list[float], pct: float) -> float | None:
    from api.brand.insights import _percentile as percentile

    return percentile([v for v in values if v is not None], pct)


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
    metrics = [c["metrics"] for c in played if c.get("metrics")]
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
    for p in posts:  # share of the reply time, for the stages
        if p["key"] in ("endpointing", "transcriber", "llm", "voice") and reply_p50:
            p["share"] = round((p["p50"] or 0) / reply_p50, 4)
    info = []
    if turns and reply_p50:
        for stage, label in INFO_STAGES.items():
            p50 = _percentile([t["stages"].get(stage, 0) for t in turns], 0.5)
            info.append(
                {
                    "key": stage,
                    "label": label,
                    "p50": p50,
                    "share": round((p50 or 0) / reply_p50, 4),
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
