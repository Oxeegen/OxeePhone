# OxeePhone changelog

OxeePhone versions are independent of the Dograh base version
(`ui/package.json`, `api/pyproject.toml`), which follows upstream. The OxeePhone
version lives in `ui/src/brand/brand.ts` and `api/brand/config.py` (a test
keeps them equal).

## Unreleased

- Installer for Ubuntu (`brand/install.sh`): Docker, code at the latest
  release, generated secrets, free ports, build, start; `update` and `status`.
- Every published port configurable in `.env` (upstream values by default) and
  container names per project: OxeePhone runs next to an official Dograh, with
  its own TURN server on its own ports.
- MinIO from the maintained community rebuild (`pgsty/minio`): the official
  images are no longer published, fresh installs could not start.
- No Cloudflare tunnel lookup without a tunnel: `/health` answered in ~6 s and
  the UI showed the backend down on LAN installs.

## 0.8.0 — 2026-10-01

First OxeePhone release, based on Dograh 1.47.0.

### Brand and privacy
- OxeePhone name, signal logo (three arcs on the Oxeegen indigo → violet
  gradient), favicon, theme; Dograh docs and community links hidden.
- No telemetry (PostHog, Sentry) and no call to Dograh-hosted services
  (model proxy, billing, managed SIP, lead forms, release check, Stripe).
- Local sessions log out cleanly on a rejected token instead of failing with 401s.

### Models (BYOK, self-hosted)
- Every service (LLM, voice, transcriber, embedding) on "Local Models":
  OpenAI-compatible base URL + key, model picked from the endpoint's list.
- Local knowledge base parsing (PDF, DOCX) and embeddings, no hosted service.
- Voice: preview, speed, language, volume gain, French number / date
  normalization and pronunciation dictionary.
- Analysis model tab (Models › Analysis).

### Agents
- Start / stop speaking plans per agent (Vapi-style): wait, smart
  endpointing, waits by transcript ending, words / voice to interrupt, back-off.
- Versions page: origin (editor, API key, MCP, restore, automatic fix),
  authors, calls per version, plain and AI summaries, word-level diffs,
  restore / publish / discard.
- Agent list: last run and published version.

### Calls and reporting
- Call detail page: recording with waveform, synced transcript, latency
  breakdown, events, analysis, usage, routing graph (path and conditions).
- Reports: latency, token consumption, quality, tools and routing indicators.

### Deployment
- One entry point for every network (`proxy` service, `brand/proxy/`): UI,
  API (HTTP + WebSocket) and recordings on the page's own origin, so the
  server works under each of its names (LAN IP, VPN hostname…) without CORS
  issues; TURN and recording URLs follow the name used; HTTPS with a generated
  certificate for all names (browsers only allow the microphone over HTTPS).

### Analysis and automatic fixes
- Configuration analysis of recorded calls: rules (latency, silences, stalled
  nodes, loops, misrouting, tools…) reviewed by the analysis model; detection
  thresholds proposed by the model and editable.
- Automatic fixes: constrained proposals (prompts, transition conditions,
  bounded settings) saved as drafts, tested by replaying real calls as text
  (tools never executed), judged, then published by a human; follow-up on real
  calls and one-click rollback.
- MCP tools (`oxee_*`) and REST routes for an AI agent with an API key; see
  `brand/agent-vm/`.
