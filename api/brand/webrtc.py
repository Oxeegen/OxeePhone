"""Server-side TURN address override.

Browsers and the API may need different addresses for the same TURN server.
On a single Docker host (Docker Desktop, or any setup where containers cannot
hairpin back to the host's published ports) the browser dials the host's
address while the API must reach coturn through the Docker network. Setting
``OXEE_SERVER_TURN_HOST`` (e.g. ``coturn``) rewrites the host of the TURN URIs
the API uses for its own peer connection; browsers keep ``TURN_HOST``.
"""

import os
import re

SERVER_TURN_HOST = os.getenv("OXEE_SERVER_TURN_HOST", "").strip()

_URI_HOST = re.compile(r"^(turns?:)([^:?]+)")


def server_turn_uris(uris: list[str]) -> list[str]:
    if not SERVER_TURN_HOST:
        return uris
    return [_URI_HOST.sub(rf"\g<1>{SERVER_TURN_HOST}", uri) for uri in uris]
