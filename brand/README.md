# OxeePhone brand layer

OxeePhone is Oxeegen's fork of [Dograh](https://github.com/dograh-hq/dograh)
(BSD-2-Clause), forked from release **v1.47.0**.

## Rules

1. **Minimal footprint on upstream files.** Brand code lives in new files only:
   - `api/brand/` — backend flags (`BRAND`) and helpers
   - `ui/src/brand/` — UI flags (`BRAND`), logo, runtime rebrander, theme CSS
   - `ui/public/brand/` — brand assets served by the UI
   - `brand/assets/` — logo sources: the signal tile (three concentric arcs on the indigo → violet gradient, variant A, generated geometry); `oxeephone-tile-variant-B/C.svg` and `logo-proposals-signal.png` keep the alternatives, `logo-proposals.png` the first round
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

The repository page shows `.github/README.md` (GitHub reads it before the root `README.md`, which stays Dograh's, untouched for merges). Screenshots and GIFs: `brand/assets/screenshots/`.

## Install / run

On an Ubuntu server (22.04 / 24.04), one command installs or completes an
install: Docker if missing, the code at the latest release, `.env` with
generated secrets (never overwritten), free ports, build, start, health check.

```bash
curl -fsSL https://raw.githubusercontent.com/Oxeegen/OxeePhone/main/brand/install.sh | sudo bash
```

From a clone: `sudo ./brand/install.sh` (install), `sudo ./brand/install.sh update`
(latest `oxeephone-v*` release, or `OXEE_REF=…`), `./brand/install.sh status`.
Every question can be answered ahead in the environment (see the header of
`brand/install.sh`), e.g. `OXEE_SERVER_IP`, `OXEE_TLS_NAMES`, `OXEE_YES=1`.

By hand, with a `.env` of your own:

```bash
docker compose -f docker-compose.yaml -f brand/docker-compose.brand.yaml --profile local-turn up -d --build
```

The overlay builds the OxeePhone images from this repo (upstream compose pulls
`dograhai/*` images, which do not contain the brand layer) and blanks every
telemetry / Dograh-hosted endpoint in the environment as a second safety net.
MinIO comes from `pgsty/minio` (MinIO no longer publishes community images;
override with `OXEE_MINIO_IMAGE`).

### Ports (`.env`, upstream values by default)

| Variable | Default | What |
|---|---|---|
| `OXEE_UI_PORT` | 3010 | Proxy HTTP (redirects to HTTPS except on localhost) |
| `OXEE_HTTPS_PORT` | 3443 | Proxy HTTPS: UI, API, MCP, recordings |
| `OXEE_API_PORT` | 8000 | Direct API: telephony webhooks, MCP, scripts |
| `OXEE_POSTGRES_PORT` / `OXEE_REDIS_PORT` | 5432 / 6379 | Published on `OXEE_DB_BIND` (default 0.0.0.0; the installer sets 127.0.0.1) |
| `OXEE_MINIO_PORT` / `OXEE_MINIO_CONSOLE_PORT` | 9000 / 9001 | MinIO, on 127.0.0.1 |
| `OXEE_TURN_PORT` / `OXEE_TURNS_PORT` | 3478 / 5349 | OxeePhone's own coturn (TCP + UDP) |
| `OXEE_TURN_RELAY_MIN` - `MAX` | 49152 - 49200 | TURN relay range (UDP), same numbers inside and outside |
| `OXEE_TUNNEL_METRICS_PORT` | 2000 | cloudflared metrics (profile `tunnel` only) |

Container names derive from the project name (`oxeephone`, or
`COMPOSE_PROJECT_NAME`), so an official Dograh can run on the same host: the
installer detects the ports it (or anything else) uses and takes the next free
ones. Volumes and networks are per project, so data stays separate.

## Flags

| Where | Flag | Default | Effect |
| --- | --- | --- | --- |
| API | `OXEE_DISABLE_DOGRAH_SERVICES` | `true` | MPS client replaced by `DisabledMPSClient`; org bootstrap (managed key, Cloudonix SIP) skipped |
| API | `OXEE_DISABLE_TELEMETRY` | `true` | PostHog and Sentry never initialised |
| API | `OXEE_LOCAL_MODELS_ONLY` | `true` | Models: BYOK pipeline only, every service on Local Models (`speaches`); `/api/v1/oxee/*` routes; recordings transcribed by the org STT |
| UI | `BRAND.enabled` | `true` | Name, logo, theme, runtime rebrand of "Dograh" in copy |
| UI | `BRAND.hideDocs` | `true` | Links to `dograh.com` / docs / GitHub / Slack hidden (`brand.css`) |
| API | `OXEE_CALL_INSIGHTS` | `true` | Persist recording-start marker, per-turn latency breakdown, interruption flag (call-detail page) |
| API | `OXEE_SPEAKING_PLAN` | `true` | Apply the agent's start/stop speaking plans (`speaking_plan` workflow config, `api/brand/speaking_plan.py`); agents without one keep the upstream turn settings |
| API | `OXEE_VERSION_HISTORY` | `true` | Agent versions: origin/author of each version (editor, API key, MCP, restore), diffs, AI summary, restore/discard (`api/brand/versions.py`, `/api/v1/oxee/workflows/{id}/versions*`) |
| API | `OXEE_AGENT_FIXES` | `true` | Automatic fixes of analysis findings (model proposal → draft → text simulation → publish; `api/brand/fixes.py`, `api/brand/simulation.py`, `/api/v1/oxee/fixes*`); simulation runs are named `OXEE-SIM-…` and left out of reports / analyses |
| API | `OXEE_TEST_CAMPAIGNS` | `true` | Test campaigns (Manage › Test campaigns; `api/brand/test_campaigns.py`, `test_runs.py`, `test_calls.py`, `/api/v1/oxee/tests/*`): scenarios written by the analysis model, played by a simulated caller by phone (tester agent, CallerID-name token → version under test on the agent side) or as text, judged, reported, compared; calls of both sides are named `OXEE-TEST-…` and left out of reports / analyses |
| API | `OXEE_AGENT_TUNING` | `true` | Call-engine settings (`api/brand/agent_tuning.py`, `/api/v1/oxee/engine-settings`): speaking plan, performance (first audio chunk, VAD, LLM temperature / max tokens, mutes) and audio & sampling (browser sample rate, output packets, end silence, recording buffer). Built-in values = what was hardcoded; platform values in Platform Settings › Call engine (org config `OXEE_ENGINE_SETTINGS`, restorable); per-agent overrides block by block (versioned), plus the agent's voice override |
| API | `OXEE_MCP_CAN_PUBLISH` | unset (false) | Adds the `oxee_publish_draft` / `oxee_rollback_fix` MCP tools (see `brand/agent-vm/README.md`) |
| API | `OXEE_SAME_ORIGIN` | `true` | Browser TURN / recording URLs on the page's origin for requests through the OxeePhone proxy; `CORS_ALLOWED_ORIGINS` honoured in OSS mode (see `brand/proxy/README.md`) |
| UI | `BRAND.sameOriginApi` | `true` | The browser calls the API on the page's origin, not the backend-reported `BACKEND_API_ENDPOINT` |
| API | `OXEE_CLOUDFLARED_TUNNEL` | `true` (`false` in the overlay) | Look for upstream's Cloudflare quick tunnel; off unless the `tunnel` profile runs (otherwise /health waits seconds on DNS) |
| API | `OXEE_UPDATE_CHECK` | `true` | The server checks the GitHub releases of `OXEE_RELEASES_REPO` (default `Oxeegen/OxeePhone`, cached 1 h) for the sidebar version: release notes and update notice |
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
- `api/services/pipecat/run_pipeline.py` — persists pipecat's `on_latency_breakdown` (minus turns falsely measured from the call start); speaking plan: VAD `start_secs`, turn start/stop strategies, stop timeout, `SpeakingPlanGate` before the output transport
- `api/services/pipecat/transcript_log_coordinator.py` — `interrupted` flag on bot messages
- `api/utils/tunnel.py` — no cloudflared lookup when `cloudflared_tunnel` is off
- `api/app.py` — OpenAPI version = `BRAND.version`; `RequestOriginMiddleware`; `CORS_ALLOWED_ORIGINS` allowlist with credentials in OSS mode when set
- `api/services/filesystem/minio.py` — public object URLs on the browser's origin (`/voice-audio/…` through the proxy)
- `api/routes/turn_credentials.py`, `api/routes/public_embed.py` — browser TURN URIs on the page's hostname
- `api/app.py` — registers the OxeePhone MCP tools (`api/brand/mcp_tools.py`) when `agent_fixes`
- `api/app.py` — `ChannelMiddleware` (request channel: editor / API key / MCP) when `version_history`
- `api/routes/workflow.py` — records version edits (update, create-draft) and publications in `api/brand/versions.py`
- `api/mcp_server/tools/save_workflow.py` — records MCP drafts (origin `mcp`)
- `api/services/workflow/pipecat_engine_custom_tools.py` — HTTP / MCP tools answered by `api/brand/simulation.tool_override` during a fix simulation (never executed)
- `api/services/workflow/pipecat_engine_custom_tools.py` — test calls: transfer-call tools simulated as answered (`test_calls.simulated_transfer`), and an HTTP tool flagged as a transfer by the simulator ends the agent's part of the call (`test_calls.transfer_by_tool`); transfer-agent tools simulated the same way; simulated HTTP tools get time to answer (`test_calls.tool_timeout`); MCP tools described to the simulator
- `api/services/workflow/text_chat_runner.py`, `api/services/pipecat/run_pipeline.py` — test calls: simulated pre-call fetch (`test_calls.pre_call_override` / `pre_call_or`); a text test call counts as inbound (`test_calls.test_direction`)
- `api/routes/webrtc_signaling.py` — server-side TURN URIs through `api/brand/webrtc.py`
- `api/services/workflow/pipecat_engine_custom_tools.py` — the tool hook goes through `api/brand/test_calls.tool_override` (fix simulations, then the campaign's tools mode during a test call: simulated / real / real with `X-Oxee-Test: 1`) when `agent_fixes` or `test_campaigns`
- `api/services/pipecat/run_pipeline.py` — test caller: per-call voice, voice speed, speaking plan and max duration (`test_calls.tester_configs`, both config resolutions); `FirstSpeechUserMuteStrategy` so it hears the agent's greeting
- `api/services/pipecat/event_handlers.py` — the test caller does not open the conversation (`test_calls.listens_first`)
- `api/services/telephony/ari_manager.py` — inbound ARI call with a test token in its CallerID name: agent, version and run name of the pending test call (`test_calls.claim_inbound`)
- `api/tasks/run_integrations.py` — no webhook or integration after a test call whose tools are simulated
- `api/services/configuration/ai_model_configuration.py` — `get_effective_ai_model_configuration_for_workflow` applies the agent's `voice_override` (`agent_tuning.apply_voice_override`)
- `api/services/pipecat/run_pipeline.py` — the agent's `performance`: VAD params, mute strategies, LLM sampling, first TTS chunk (`agent_tuning`)
- `ui/src/app/workflow/[workflowId]/settings/page.tsx` — speaking plan, voice, performance, audio blocks from `@/brand/AgentEngineBlocks` (platform settings unless overridden)
- `api/services/pipecat/run_pipeline.py` — platform call-engine blocks merged into the run configuration (`agent_tuning.effective_configs`), audio config (sample rate, recording buffer) and transport output params (packets, end silence)
- `api/services/pipecat/agent_runtime_factory.py` — an agent taking over a call (transfer) gets its call-engine settings too (`agent_tuning.tune_services`)
- `ui/src/app/recordings/page.tsx`, `ui/src/app/recordings/RecordingsList.tsx` — Generate button and "use as greeting" row action (`@/brand/RecordingTools`, `api/brand/recordings.py`)
- `api/services/pipecat/event_handlers.py` — the test caller's pipeline (phone test calls) ends without logs, artifacts or completion job (`test_calls.tester_of`); `test_runs` deletes its run
- `api/services/pipecat/run_pipeline.py` — voice statistics of each sentence (`LocalModelsTTSService.oxee_on_voice_stats`) appended to the run logs as `oxee-voice-stats`
- `ui/src/app/files/DocumentList.tsx` — preview button (`@/brand/FilePreview`, `api/brand/files.py`); `ui/package.json` adds `react-markdown` and `remark-gfm` for it
- `ui/src/app/tools/page.tsx`, `ui/src/app/files/DocumentList.tsx`, `ui/src/app/recordings/RecordingsList.tsx` — clear button and Escape on the search field (`@/brand/ClearSearch`)
- `ui/src/app/settings/page.tsx` — Call engine settings (`@/brand/EngineSettingsCard`) instead of Telemetry (Langfuse)
- `ui/src/components/layout/AppSidebar.tsx` — Platform settings and Sign out as menu entries at the bottom, not behind the initials
- `ui/src/components/workflow/WorkflowTable.tsx`, `ui/src/app/campaigns/page.tsx`, `ui/src/app/usage/page.tsx`, `ui/src/components/workflow-runs/WorkflowRunsTable.tsx` — the whole row opens the page (`@/brand/rowLink`); redundant Edit / View / open buttons hidden

**UI**
- `ui/src/components/layout/AppSidebar.tsx` — Manage › Analysis and Manage › Test campaigns (`ui/src/app/test-campaigns`, `ui/src/brand/tests`)
- `ui/src/components/layout/AppSidebar.tsx` — the OxeePhone version (`@/brand/release/VersionBadge`): release notes of the running version, update notice and command (`GET /api/v1/oxee/releases`)
- `ui/src/lib/apiClient.ts` — `resolveBrowserBackendUrl` ignores the backend-reported endpoint when `sameOriginApi`
- `ui/src/app/favicon.ico` — replaced by the OxeePhone icon (binary, not gated)
- `ui/src/app/layout.tsx` — brand CSS, metadata, `<BrandRuntime/>`, no Chatwoot
- `ui/src/components/BrandLogo.tsx` — delegates to `@/brand/BrandLogo`
- `ui/src/components/auth/AuthShell.tsx` — headline, highlights, no enterprise CTA
- `ui/src/components/Footer.tsx` — hidden (dograh.com privacy/terms)
- `ui/src/components/layout/AppLayout.tsx` — no Slack community link
- `ui/src/components/layout/AppSidebar.tsx` — no Billing entry, no "Hire an Expert", MANAGE › Analysis entry
- `ui/src/app/analysis/page.tsx` — new route rendering `@/brand/analysis/AnalysisPage` (configuration analysis; `api/brand/analysis.py`, `/api/v1/oxee/analysis/*`)
- `ui/src/components/layout/GitHubStarBadge.tsx` — hidden, no GitHub API call
- `ui/src/app/overview/page.tsx` — welcome copy, no Dograh resources card
- `ui/src/instrumentation-client.ts`, `ui/src/app/api/config/{posthog,sentry}/route.ts` — telemetry off
- `ui/src/components/lead-forms/onboardingServiceClient.ts`, `HireExpertNudge.tsx`, `ui/src/context/LeadFormsContext.tsx` — no lead forms
- `ui/src/hooks/useLatestReleaseVersion.ts` — no release check
- `ui/src/components/AIModelConfigurationV2Editor.tsx` — BYOK only, no mode tabs, no third-party notice; passes `showAnalysisTab`
- `ui/src/components/ModelConfigurationV2.tsx` — `showAnalysisTab` on the org Models page only (not workflow overrides)
- `ui/src/components/ServiceConfigurationForm.tsx` — `showAnalysisTab` (Models › Analysis, saved with the form); Base URL in place of the provider select, `@/brand/LocalModelPicker` for `model`, keyless embeddings saved; Voice tab uses `@/brand/LocalVoiceControls` (voice + Listen preview, speed slider)
- `ui/src/app/files/DocumentUpload.tsx` — no "sent to Dograh" notice, no `.doc`
- `ui/src/app/workflow/[workflowId]/run/[runId]/page.tsx` — renders `@/brand/call-detail/CallDetailPage` (VAPI-style call detail, incl. Routing tab fed by `GET /api/v1/oxee/runs/{id}/routing`)
- `ui/src/app/workflow/[workflowId]/settings/page.tsx` — Start / Stop speaking plans (`@/brand/SpeakingPlanSection`) in place of Turn Detection / Interruption; saves `speaking_plan` plus the matching upstream turn keys
- `ui/src/components/workflow/WorkflowTable.tsx` — Last Run and Published Version columns (`@/brand/agents/AgentListInfo`, `GET /api/v1/oxee/workflows/list-info`); Total Runs without the fix simulations
- `ui/src/app/workflow/[workflowId]/versions/page.tsx` — new route rendering `@/brand/versions/VersionsPage` (versions list, summary + AI summary, detailed diff, restore / publish / discard)
- `ui/src/app/workflow/[workflowId]/RenderWorkflow.tsx`, `components/VersionHistoryPanel.tsx` — optional `versionsPageHref` link in the history panel
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

## Versions

OxeePhone releases are numbered on their own (`BRAND.version`, UI and API kept equal by a test); see `brand/CHANGELOG.md`. Release tags are `oxeephone-vX.Y.Z` (upstream tags are `dograh-v*`). The GitHub release body is what the app shows as release notes: publish each release with its `brand/CHANGELOG.md` section.

## Test campaigns by phone (Asterisk)

The tester is an agent created automatically ("OxeePhone test caller", one
start node whose prompt is the persona, one hang-up node; repaired if edited).
A phone execution needs, in Manage › Test campaigns › Test settings:

- the tester's telephony configuration (e.g. a second ARI configuration);
- the agent's inbound number (Telephony › Phone numbers, routed to the agent),
  or a dedicated test number;
- pools of caller numbers and voices (ids of your voice model, with gender).

Asterisk side: the tester's dial template must reach the agent's extension, the
agent's dial plan must not `Answer()` before `Stasis()`, and the CallerID
**name** must reach the agent's channel intact: it carries the one-time token
(`"OXT<token>" <customer number>`) that makes the agent run the version under
test. Each test call holds two lines (caller + agent) of the organization's
concurrency limit. Text executions need none of this.

