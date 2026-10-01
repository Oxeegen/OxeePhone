"""Same-origin access from several networks (LAN IP, VPN hostname…).

Upstream advertises one absolute address per deployment (BACKEND_API_ENDPOINT,
TURN_HOST, MINIO_PUBLIC_ENDPOINT). A server reached under several names (e.g.
``10.100.21.41`` on the LAN and ``sngi-ai-phone-01.nb.us`` over NetBird) can
only satisfy one of them: the others get CORS errors, a dead WebSocket, an
unreachable TURN server or broken recording links.

With the OxeePhone proxy (``brand/proxy/nginx.conf``: one port for the UI,
``/api/v1`` HTTP + WebSocket and ``/voice-audio`` recordings) the browser stays
on the origin it loaded the page from. The proxy marks the requests it
forwards (``X-Oxee-Proxy: 1``, original ``Host`` kept); for those requests the
API answers with addresses built on that origin:

- TURN URIs for the browser use the page's hostname (coturn listens on every
  interface of the host);
- recording / upload URLs use ``<origin>/voice-audio/…`` (proxied to MinIO).

Requests that reach the API directly (port 8000: webhooks, MCP, scripts) keep
the configured absolute values.
"""

from __future__ import annotations

import contextvars
import re

_origin: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "oxee_request_origin", default=None
)

PROXY_HEADER = "x-oxee-proxy"
_HOST = re.compile(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$|^\[[0-9A-Fa-f:.]+\](:\d{1,5})?$")
_URI_HOST = re.compile(r"^(turns?:)([^:?]+)")


class RequestOriginMiddleware:
    """Remembers the browser's origin for requests coming through the proxy."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {
            k.decode().lower(): v.decode() for k, v in scope.get("headers") or []
        }
        origin = None
        if headers.get(PROXY_HEADER) == "1":
            host = headers.get("x-forwarded-host") or headers.get("host") or ""
            proto = (headers.get("x-forwarded-proto") or "http").split(",")[0].strip()
            if _HOST.match(host) and proto in ("http", "https"):
                origin = f"{proto}://{host}"
        token = _origin.set(origin)
        try:
            await self.app(scope, receive, send)
        finally:
            _origin.reset(token)


def request_origin() -> str | None:
    """``scheme://host[:port]`` the browser used, when it came through the proxy."""
    return _origin.get()


def request_hostname() -> str | None:
    origin = _origin.get()
    if not origin:
        return None
    host = origin.split("://", 1)[1]
    if host.startswith("["):  # IPv6 literal
        return host[: host.index("]") + 1]
    return host.rsplit(":", 1)[0] if ":" in host else host


def media_base(default: str) -> str:
    """Base URL for MinIO objects (``<base>/<bucket>/<key>``)."""
    return request_origin() or default


def browser_turn_uris(uris: list[str]) -> list[str]:
    """TURN URIs on the hostname the browser used to reach the page."""
    host = request_hostname()
    if not host:
        return uris
    return [_URI_HOST.sub(rf"\g<1>{host}", uri) for uri in uris]
