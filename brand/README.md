# OxeePhone brand layer

OxeePhone is Oxeegen's fork of [Dograh](https://github.com/dograh-hq/dograh)
(BSD-2-Clause), forked from release **v1.47.0**.

## Rules

1. **Minimal footprint on upstream files.** Brand code lives in new files only:
   - `api/brand/` — backend flags (`BRAND`) and helpers
   - `ui/src/brand/` — UI flags (`BRAND`), logo, runtime rebrander, theme CSS
   - `ui/public/brand/` — brand assets served by the UI
   - `brand/assets/` — logo sources (direction B "Signal"; `logo-proposals.png` keeps the other options)
   - `brand/` — deployment overlay and this guide
2. **Every edit to an upstream file is gated** by a `BRAND` flag and keeps the
   upstream behaviour when the flag is off (`BRAND.enabled` in the UI,
   `OXEE_DISABLE_*` env vars on the API).
3. **Sync upstream by merge, never rebase.** `upstream-tracking` mirrors
   `dograh-hq/dograh` `main`; the upstream remote has push disabled.

```bash
git fetch upstream --tags
git merge dograh-vX.Y.Z   # merge a release tag, then re-check the patch list below
```

## Run

```bash
docker compose -f docker-compose.yaml -f brand/docker-compose.brand.yaml up -d --build
```

The overlay builds the OxeePhone images from this repo (upstream compose pulls
`dograhai/*` images, which do not contain the brand layer) and blanks every
telemetry / Dograh-hosted endpoint in the environment as a second safety net.

## Flags

| Where | Flag | Default | Effect |
| --- | --- | --- | --- |
| API | `OXEE_DISABLE_DOGRAH_SERVICES` | `true` | MPS client replaced by `DisabledMPSClient`; org bootstrap (managed key, Cloudonix SIP) skipped |
| API | `OXEE_DISABLE_TELEMETRY` | `true` | PostHog and Sentry never initialised |
| API | `OXEE_LOCAL_MODELS_ONLY` | `true` | Models: BYOK pipeline only, every service on Local Models (`speaches`); `/api/v1/oxee/*` routes; recordings transcribed by the org STT |
| UI | `BRAND.enabled` | `true` | Name, logo, theme, runtime rebrand of "Dograh" in copy |
| UI | `BRAND.hideDocs` | `true` | Links to `dograh.com` / docs / GitHub / Slack hidden (`brand.css`) |
| API | `OXEE_CALL_INSIGHTS` | `true` | Persist recording-start marker, per-turn latency breakdown, interruption flag (call-detail page) |
| API | `OXEE_SERVER_TURN_HOST` | unset | Host the API uses for TURN when it differs from the browsers' `TURN_HOST` (single Docker host: `coturn`) |
| UI | `BRAND.localModelsOnly` | `true` | No mode tabs / provider choice; Base URL + model list from the endpoint (must match `OXEE_LOCAL_MODELS_ONLY`) |
| UI | `BRAND.disableDograhServices` | `true` | No PostHog, Sentry, Chatwoot, lead forms, GitHub badge, release check, Billing entry |

## Gated patches on upstream files

Re-check each of these after an upstream merge (grep for `BRAND` / `brand`).

**API**
- `api/app.py` — Sentry gate, OpenAPI title/description/servers
- `api/errors/mps.py` — public message when a Dograh-hosted feature is used
- `api/mcp_server/server.py` — MCP server name
- `api/services/mps_service_key_client.py` — singleton swapped for `DisabledMPSClient`
- `api/services/organization_bootstrap.py` — early return (no managed provisioning)
- `api/services/posthog_client.py` — `get_posthog()` returns `None`
- `api/requirements.txt` — `pypdf`, `python-docx` (local document parsing)
- `api/services/configuration/registry.py` — new `SpeachesEmbeddingsConfiguration` (not gated: an extra provider, inert upstream)
- `api/services/configuration/registry.py` — `language`, `volume_gain_db`, `pronunciations` fields on `SpeachesTTSConfiguration` (not gated: inert upstream)
- `api/services/pipecat/service_factory.py` — Speaches TTS built as `api/brand/tts.py` `LocalModelsTTSService` (forwards `language`; pronunciation dictionary + French normalization from `api/brand/speech_text.py` on the synthesis text only; gain on the PCM)
- `api/services/gen_ai/embedding/factory.py` — `speaches` → `api/brand/embeddings.py` (zero-padded to 1536)
- `api/tasks/knowledge_base_processing.py` — local parsing/chunking (`api/brand/documents.py`) instead of MPS; no API key needed for Local Models
- `api/services/workflow/tools/knowledge_base.py` — no API key needed for Local Models
- `api/routes/main.py` — mounts `api/brand/routes.py` (`/api/v1/oxee/*`: models, TTS preview, call routing graphs)
- `api/routes/organization.py` — schemas restricted to Local Models, default providers, save-time enforcement
- `api/routes/workflow.py` — same enforcement on workflow model overrides
- `api/routes/workflow_recording.py` — transcription through the org STT
- `api/services/pipecat/event_handlers.py` — recording-start marker on client connect (best effort)
- `api/services/pipecat/run_pipeline.py` — persists pipecat's `on_latency_breakdown`
- `api/services/pipecat/transcript_log_coordinator.py` — `interrupted` flag on bot messages
- `api/routes/webrtc_signaling.py` — server-side TURN URIs through `api/brand/webrtc.py`

**UI**
- `ui/src/app/favicon.ico` — replaced by the OxeePhone icon (binary, not gated)
- `ui/src/app/layout.tsx` — brand CSS, metadata, `<BrandRuntime/>`, no Chatwoot
- `ui/src/components/BrandLogo.tsx` — delegates to `@/brand/BrandLogo`
- `ui/src/components/auth/AuthShell.tsx` — headline, highlights, no enterprise CTA
- `ui/src/components/Footer.tsx` — hidden (dograh.com privacy/terms)
- `ui/src/components/layout/AppLayout.tsx` — no Slack community link
- `ui/src/components/layout/AppSidebar.tsx` — no Billing entry, no "Hire an Expert"
- `ui/src/components/layout/GitHubStarBadge.tsx` — hidden, no GitHub API call
- `ui/src/app/overview/page.tsx` — welcome copy, no Dograh resources card
- `ui/src/instrumentation-client.ts`, `ui/src/app/api/config/{posthog,sentry}/route.ts` — telemetry off
- `ui/src/components/lead-forms/onboardingServiceClient.ts`, `HireExpertNudge.tsx`, `ui/src/context/LeadFormsContext.tsx` — no lead forms
- `ui/src/hooks/useLatestReleaseVersion.ts` — no release check
- `ui/src/components/AIModelConfigurationV2Editor.tsx` — BYOK only, no mode tabs, no third-party notice
- `ui/src/components/ServiceConfigurationForm.tsx` — Base URL in place of the provider select, `@/brand/LocalModelPicker` for `model`, keyless embeddings saved; Voice tab uses `@/brand/LocalVoiceControls` (voice + Listen preview, speed slider)
- `ui/src/app/files/DocumentUpload.tsx` — no "sent to Dograh" notice, no `.doc`
- `ui/src/app/workflow/[workflowId]/run/[runId]/page.tsx` — renders `@/brand/call-detail/CallDetailPage` (VAPI-style call detail, incl. Routing tab fed by `GET /api/v1/oxee/runs/{id}/routing`)
- `ui/src/app/reports/page.tsx` — appends `@/brand/reports/CallInsights` (latency, consumption, quality, tools, routing; `GET /api/v1/oxee/reports/insights`)
- `ui/src/context/OrgConfigContext.tsx` — registers `@/brand/sessionGuard` (local auth: log out on the first backend 401 instead of leaving every page failing)
- `ui/next.config.ts` — aliases `@stripe/stripe-js` to `src/brand/stubs/stripe-js.ts` (Stack Auth would otherwise load js.stripe.com + fingerprinting on `/`, `/after-sign-in`, `/workflow`)

## Do not rename

Internal identifiers stay as upstream so data and integrations keep working:
`ServiceProviders.DOGRAH`, `X-Dograh-*` webhook headers, `DOGRAH_*` env vars,
`dograh_auth_*` cookies, `sdk/`, `deploy/helm/dograh`, `window.DograhWidget`.

## Tests

```bash
# upstream suite, upstream behaviour
OXEE_DISABLE_DOGRAH_SERVICES=false OXEE_DISABLE_TELEMETRY=false \
  python -m pytest -c api/pytest.ini --rootdir api api/tests
# brand gates (force the flags on themselves)
python -m pytest -c api/pytest.ini --rootdir api api/tests/brand
```

## Local web calls (Docker Desktop)

Containers cannot reach the host's published UDP ports here, so WebRTC media
must go through coturn *inside* the Docker network. Machine-local, not
committed: in `.env` set `ENABLE_COTURN=true`, `TURN_SECRET`, `TURN_HOST=<LAN
IP>`, `FORCE_TURN_RELAY=true`; in `docker-compose.local.yaml` set
`OXEE_SERVER_TURN_HOST: coturn` on `api` and mount a `turnserver.conf` without
`external-ip` on `coturn`; start with `--profile local-turn`.
