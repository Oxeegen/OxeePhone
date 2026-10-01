"""OxeePhone: update check against the GitHub releases."""

import pytest

from api.brand import releases

RAW = [
    {
        "tag_name": "oxeephone-v0.8.0",
        "name": "OxeePhone 0.8.0",
        "html_url": "u080",
        "published_at": "2026-10-01",
        "body": "first",
    },
    {
        "tag_name": "oxeephone-v0.10.0",
        "name": "OxeePhone 0.10.0",
        "html_url": "u0100",
        "published_at": "2026-11-01",
        "body": "big",
    },
    {
        "tag_name": "oxeephone-v0.9.0",
        "name": "OxeePhone 0.9.0",
        "html_url": "u090",
        "published_at": "2026-10-15",
        "body": "next",
    },
    {"tag_name": "oxeephone-v1.0.0-rc1", "name": "rc", "body": "ignored: not semver"},
    {
        "tag_name": "oxeephone-v0.11.0",
        "name": "beta",
        "prerelease": True,
        "body": "pre",
    },
    {"tag_name": "oxeephone-v0.12.0", "name": "draft", "draft": True},
    {"tag_name": "dograh-v1.48.0", "name": "upstream"},
]


def _parsed():
    found = [r for r in (releases._release(x) for x in RAW) if r]
    return sorted(
        found, key=lambda r: releases.parse_version(r["version"]), reverse=True
    )


def test_versions_compare_numerically_and_skip_others():
    assert [r["version"] for r in _parsed()] == ["0.11.0", "0.10.0", "0.9.0", "0.8.0"]


def test_summary_for_an_old_install():
    s = releases.summary(_parsed(), None, current="0.8.0")
    assert s["update_available"] is True
    assert s["latest"]["version"] == "0.10.0"  # prereleases are not offered
    assert [r["version"] for r in s["newer"]] == ["0.10.0", "0.9.0"]
    assert s["current_release"]["notes"] == "first"


def test_summary_when_up_to_date_or_offline():
    s = releases.summary(_parsed(), None, current="0.10.0")
    assert s["update_available"] is False and s["newer"] == []
    off = releases.summary(
        None, "GitHub could not be reached from the server", current="0.8.0"
    )
    assert (
        off["update_available"] is False
        and off["current_release"] is None
        and off["error"]
    )


@pytest.mark.asyncio
async def test_results_are_cached(monkeypatch):
    calls = []

    async def fetch():
        calls.append(1)
        return _parsed()

    monkeypatch.setattr(releases, "_fetch", fetch)
    monkeypatch.setattr(
        releases, "_cache", {"at": 0.0, "releases": None, "error": None}
    )
    await releases.releases()
    await releases.releases()
    assert len(calls) == 1
    await releases.releases(force=True)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_failures_are_reported_not_raised(monkeypatch):
    async def fetch():
        raise OSError("no route to host")

    monkeypatch.setattr(releases, "_fetch", fetch)
    monkeypatch.setattr(
        releases, "_cache", {"at": 0.0, "releases": None, "error": None}
    )
    found, error = await releases.releases()
    assert found is None and "GitHub" in error
