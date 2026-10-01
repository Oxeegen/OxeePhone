# One entry point for every network (LAN, VPN…)

Upstream advertises one absolute address per deployment (`BACKEND_API_ENDPOINT`,
`TURN_HOST`, `MINIO_PUBLIC_ENDPOINT`). A server reached under several names —
`10.100.21.41` on the LAN, `sngi-ai-phone-01.nb.us` over NetBird — can only
satisfy one: the others get "CORS" errors (the API name does not resolve from
their network), a dead signaling WebSocket (the Next.js proxy does not pass
WebSocket upgrades), an unreachable TURN server and broken recording links.
And over plain HTTP on anything but `localhost`, browsers give the page **no
microphone** (not a secure context), so web calls cannot even start.

The `proxy` service of `brand/docker-compose.brand.yaml` fixes all of it:

| Path | Goes to |
|---|---|
| `/api/v1/*` (HTTP, SSE, MCP, **WebSocket**) | `api:8000` |
| `/voice-audio/*` (recordings, transcripts, uploads) | `minio:9000` |
| `/oxee-ca.crt` | the certificate authority to install (see below) |
| everything else | `ui:3010` |

- The browser stays on the origin it loaded the page from (the UI ignores the
  backend-reported `BACKEND_API_ENDPOINT`; `NEXT_PUBLIC_BACKEND_URL` still wins
  if you build with it).
- The API builds the browser's TURN URIs and recording URLs on that same name
  (`api/brand/origin.py`, only for requests marked by the proxy).
- `BACKEND_API_ENDPOINT`, `TURN_HOST`, `MINIO_PUBLIC_ENDPOINT` keep their
  server-side uses (telephony webhooks, links in e-mails / webhooks, the API's
  own WebRTC peer). Port 8000 stays published for webhooks, MCP and scripts.

## Configuration (`.env`)

```bash
# Every name users type to reach the server, for the HTTPS certificate.
OXEE_TLS_NAMES=10.100.21.41,sngi-ai-phone-01.nb.us
# Optional (defaults shown)
OXEE_HTTP_PORT=3010          # http://localhost:3010 works as before
OXEE_HTTPS_PORT=3443         # https://<any name>:3443 for everyone else
OXEE_HTTPS_REDIRECT=true     # http on another name than localhost -> https
# CORS_ALLOWED_ORIGINS=https://intranet.example.com   # only if another site must call the API cross-origin (with credentials)
```

`TURN_HOST` must still be set (server side) and coturn's ports open on every
network (3478 tcp/udp, 49152-49200/udp): browsers dial TURN on the name they
use for the page.

```bash
docker compose -f docker-compose.yaml -f brand/docker-compose.brand.yaml --profile local-turn up -d
```

Users open `https://10.100.21.41:3443` or `https://sngi-ai-phone-01.nb.us:3443`.

## Certificate

At start the proxy keeps, in the `oxeephone-certs` volume, a small local
certificate authority and a server certificate for `localhost`, `127.0.0.1`
and `OXEE_TLS_NAMES` (made again when the list changes).

- **Trust it once per machine**: download `https://<server>:3443/oxee-ca.crt`
  (accept the warning that one time) and install it as a trusted root
  authority (Windows: double-click › Install › Local Machine › Trusted Root
  Certification Authorities; macOS: Keychain Access › System › Always Trust;
  Linux/Chrome: Settings › Privacy › Certificates › Authorities › Import).
  Without it, browsers show a warning each session but calls still work after
  "Continue".
- **Your own certificate** (company CA, Let's Encrypt…): put `server.crt`
  (full chain) and `server.key` in the `oxeephone-certs` volume and set
  `OXEE_TLS_CUSTOM=true`.
