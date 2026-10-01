"""OxeePhone releases: is a newer version out, and what changed.

Reads the GitHub releases of the OxeePhone repository (tags
``oxeephone-vX.Y.Z``) from the server, cached, so browsers stay on the page's
origin and a server without internet access only loses this panel. Off with
``OXEE_UPDATE_CHECK=false``.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

import httpx
from loguru import logger

from api.brand.config import BRAND, _env_flag

REPO = os.getenv("OXEE_RELEASES_REPO", "Oxeegen/OxeePhone").strip()
ENABLED = _env_flag("OXEE_UPDATE_CHECK", True)
CACHE_SECONDS = 3600
FAILURE_CACHE_SECONDS = 600
TAG = re.compile(r"^oxeephone-v(\d+)\.(\d+)\.(\d+)$")

_cache: dict[str, Any] = {"at": 0.0, "releases": None, "error": None}


def parse_version(value: str | None) -> tuple[int, int, int] | None:
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", (value or "").strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def _release(raw: dict) -> dict | None:
    m = TAG.match(raw.get("tag_name") or "")
    if not m or raw.get("draft"):
        return None
    return {
        "version": f"{m[1]}.{m[2]}.{m[3]}",
        "tag": raw["tag_name"],
        "name": raw.get("name") or raw["tag_name"],
        "url": raw.get("html_url"),
        "published_at": raw.get("published_at"),
        "prerelease": bool(raw.get("prerelease")),
        "notes": raw.get("body") or "",
    }


async def _fetch() -> list[dict]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(6.0)) as client:
        response = await client.get(
            f"https://api.github.com/repos/{REPO}/releases",
            params={"per_page": 30},
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"{BRAND.product_name}/{BRAND.version}",
            },
        )
    response.raise_for_status()
    releases = [r for r in (_release(x) for x in response.json()) if r]
    return sorted(releases, key=lambda r: parse_version(r["version"]), reverse=True)


async def releases(*, force: bool = False) -> tuple[list[dict] | None, str | None]:
    """Cached releases, newest first, or (None, error)."""
    age = time.monotonic() - _cache["at"]
    ttl = FAILURE_CACHE_SECONDS if _cache["error"] else CACHE_SECONDS
    if not force and _cache["at"] and age < ttl:
        return _cache["releases"], _cache["error"]
    try:
        found, error = await _fetch(), None
    except Exception as e:  # offline, rate limited, repo renamed...
        logger.info(f"OxeePhone release check failed: {e}")
        found, error = None, "GitHub could not be reached from the server"
    _cache.update(at=time.monotonic(), releases=found, error=error)
    return found, error


def summary(
    found: list[dict] | None, error: str | None, current: str = BRAND.version
) -> dict:
    """What the UI shows: current release notes, newer releases, latest."""
    stable = [r for r in found or [] if not r["prerelease"]]
    cur = parse_version(current)
    newer = [r for r in stable if cur and parse_version(r["version"]) > cur]
    latest = stable[0] if stable else None
    return {
        "enabled": True,
        "repository": REPO,
        "current": current,
        "current_release": next(
            (r for r in found or [] if r["version"] == current), None
        ),
        "latest": (
            {k: latest[k] for k in ("version", "tag", "name", "url", "published_at")}
            if latest
            else None
        ),
        "update_available": bool(newer),
        "newer": newer,
        "error": error,
    }


async def release_info(*, force: bool = False) -> dict:
    if not ENABLED:
        return {
            "enabled": False,
            "repository": REPO,
            "current": BRAND.version,
            "update_available": False,
            "newer": [],
        }
    found, error = await releases(force=force)
    return summary(found, error)
