"""OxeePhone: same-origin access from several networks (api/brand/origin.py)."""

import pytest

from api.brand import origin


async def _seen(headers, path="/api/v1/turn/credentials"):
    seen = {}

    async def app(scope, receive, send):
        seen["origin"] = origin.request_origin()
        seen["host"] = origin.request_hostname()
        seen["turn"] = origin.browser_turn_uris(
            [
                "turn:10.0.0.5:3478",
                "turn:10.0.0.5:3478?transport=tcp",
                "turns:10.0.0.5:5349",
            ]
        )
        seen["media"] = origin.media_base("http://localhost:9000")

    await origin.RequestOriginMiddleware(app)(
        {
            "type": "http",
            "path": path,
            "headers": [(k.encode(), v.encode()) for k, v in headers],
        },
        None,
        None,
    )
    return seen


@pytest.mark.asyncio
async def test_through_the_proxy_everything_follows_the_page_origin():
    seen = await _seen([("host", "sngi-ai-phone-01.nb.us:3010"), ("x-oxee-proxy", "1")])
    assert seen["origin"] == "http://sngi-ai-phone-01.nb.us:3010"
    assert seen["turn"] == [
        "turn:sngi-ai-phone-01.nb.us:3478",
        "turn:sngi-ai-phone-01.nb.us:3478?transport=tcp",
        "turns:sngi-ai-phone-01.nb.us:5349",
    ]
    assert seen["media"] == "http://sngi-ai-phone-01.nb.us:3010"


@pytest.mark.asyncio
async def test_lan_ip_and_https():
    seen = await _seen(
        [
            ("host", "10.100.21.41:3010"),
            ("x-oxee-proxy", "1"),
            ("x-forwarded-proto", "https"),
        ]
    )
    assert (
        seen["origin"] == "https://10.100.21.41:3010" and seen["host"] == "10.100.21.41"
    )


@pytest.mark.asyncio
async def test_ipv6_literal():
    seen = await _seen([("host", "[fde7::1]:3010"), ("x-oxee-proxy", "1")])
    assert seen["host"] == "[fde7::1]"
    assert seen["turn"][0] == "turn:[fde7::1]:3478"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        [("host", "10.100.21.41:8000")],  # direct call: configured values
        [("host", "evil.example/<script>"), ("x-oxee-proxy", "1")],  # malformed host
        [
            ("host", "a.example"),
            ("x-oxee-proxy", "1"),
            ("x-forwarded-proto", "javascript"),
        ],
    ],
)
async def test_configured_values_otherwise(headers):
    seen = await _seen(headers)
    assert seen["origin"] is None
    assert seen["turn"][0] == "turn:10.0.0.5:3478"
    assert seen["media"] == "http://localhost:9000"
