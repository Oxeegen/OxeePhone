"""Home page KPIs: calls of the day, average quality and technical scores
(``api/brand/call_scoring.py``), against the day before and the last 7 days.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from statistics import mean
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAYS = 7


def _avg(values: list[float]) -> float | None:
    values = [v for v in values if isinstance(v, (int, float))]
    return round(mean(values), 2) if values else None


def summarize(runs: list[dict], tz: ZoneInfo, now: datetime) -> dict:
    today = now.astimezone(tz).date()
    days = [today - timedelta(days=i) for i in range(DAYS - 1, -1, -1)]
    by_day: dict = defaultdict(list)
    for r in runs:
        by_day[r["created_at"].astimezone(tz).date()].append(r)

    def stats(rows: list[dict]) -> dict:
        scores = [r["score"] for r in rows if r.get("score")]
        return {
            "calls": len(rows),
            "scored": len(scores),
            "quality": _avg([((s.get("quality") or {}).get("score")) for s in scores]),
            "technical": _avg([((s.get("technical") or {}).get("score")) for s in scores]),
            "resolved_rate": (
                round(
                    sum(1 for s in scores if (s.get("quality") or {}).get("resolved"))
                    / len([s for s in scores if s.get("quality")]),
                    3,
                )
                if any(s.get("quality") for s in scores)
                else None
            ),
            "minutes": round(sum(r.get("duration") or 0 for r in rows) / 60, 1),
        }

    week = [r for d in days for r in by_day.get(d, [])]
    return {
        "today": {"date": today.isoformat(), **stats(by_day.get(today, []))},
        "yesterday": stats(by_day.get(today - timedelta(days=1), [])),
        "week": stats(week),
        "daily": [{"date": d.isoformat(), **stats(by_day.get(d, []))} for d in days],
        "unscored": sum(
            1 for r in week if r.get("is_completed") and not r.get("score")
        ),
    }


async def overview_kpis(organization_id: int, tz_name: str) -> dict:
    from api.brand import db as brand_db

    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    now = datetime.now(UTC)
    since = (now.astimezone(tz) - timedelta(days=DAYS + 1)).astimezone(UTC)
    runs = await brand_db.scored_runs_since(organization_id, since)
    return {"timezone": str(tz), **summarize(runs, tz, now)}
