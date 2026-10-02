# OxeePhone changelog

OxeePhone versions are independent of the Dograh base version
(`ui/package.json`, `api/pyproject.toml`), which follows upstream. The OxeePhone
version lives in `ui/src/brand/brand.ts` and `api/brand/config.py` (a test
keeps them equal).

## 0.9.3 — 2026-10-02

- Test campaigns by phone: the test caller no longer stays silent when it
  misses the agent's greeting (the agent answers and greets while the
  caller's pipeline is still starting). After 6 s without having spoken or
  heard anything, it opens the conversation itself.
- Test settings › Pairing: "arrival order" for PBXs and trunks that drop the
  CallerID name; the agent side then takes the oldest pending test call, and
  executions place one call at a time. The error of an unpaired call says so.

## 0.9.2 — 2026-10-02

- Installer: images built one at a time with up to three attempts (the UI
  build crashed now and then next to the API build); `update` builds and
  starts with the installer of the version it fetched.

## 0.9.1 — 2026-10-02

- **Agent voice** (agent settings): voice, speed, language and volume of one
  agent on top of the organization's voice model, with a Listen button. Unlike
  the model override, the agent keeps the organization's endpoint, key and
  model.
- **Performance settings**: audio received before the first sound is
  played (pipecat waited for 500 ms of audio), voice detection (end-of-speech
  silence, confidence, minimum volume), LLM temperature and maximum reply
  length, listening while a tool runs or during the first reply. Unset values
  keep the built-in behaviour.
- **Audio & sampling**: sample rate of browser calls (8 / 16 kHz; phone calls
  keep the operator's rate), output audio packets, silence before hanging up,
  recording assembly interval.
- **Platform Settings › Call engine**: the speaking plan, performance and audio
  values every agent uses, with "Restore built-in values" (what was
  hardcoded). In the agent settings each block (speaking plan, voice,
  performance, audio) follows the platform unless overridden; overrides are
  stored in the agent's version (diffs, restore, test-campaign comparisons).
  A test execution records the platform values in force; a comparison lists
  those that changed.
- Platform settings and sign out are entries at the bottom of the menu; the
  Langfuse telemetry section is gone.
- Lists (agents, campaigns, test campaigns, executions, runs): the whole row
  opens the page (Ctrl / Cmd-click: new tab); the redundant buttons are gone.

## 0.9.0 — 2026-10-02

- **Test campaigns** (Manage › Test campaigns). Pick an agent and set each
  caller setting as a min / max range (vocabulary, mood, request clarity,
  complexity, depth in the agent, impatience, dictated data, traps, voice
  speed); the analysis model writes the scenarios from the agent's graph: one
  caller each, with a full persona, the facts it can give, success criteria,
  forbidden behaviours, expected end node, variables and tools. Scenarios are
  editable, can be duplicated into variants and switched off.
- Play a campaign on the published version, the draft or an older version, by
  phone (a tester agent calls the agent with its own voice, voice speed and
  impatience, from a real customer number of the pool) or as text (no
  telephony). Each scenario can be played several times to spot unstable
  ones. The agent's tools are simulated (default), real, or real with an
  `X-Oxee-Test: 1` header.
- Each call is judged (goal, criteria with evidence, forbidden behaviours,
  quality scores, scenario at fault) and checked against the call data (end
  node, tools, extracted variables). The report gives the pass rate by
  scenario and by caller setting, latency per stage, interruptions, tools,
  coverage of the agent's nodes and transitions, and what fails; a failed call
  turns into an automatic fix.
- Two scores per execution and per call: a **quality score** (mean of the
  judge's 1-5 scores) and a **technical score**. The technical report grades
  each post (reply time, greeting, end-of-turn detection, transcriber, LLM,
  voice, tools, turn-taking, reliability) 1-5 against the Analysis
  thresholds, with median, p90, max, share of the reply time and models.
- Compare two executions: quality and technical scores side by side with their
  detail, indicators, scenarios improved or regressed, coverage, and the
  configuration diff between the two versions tested.
- Test calls stay out of the production reports and analyses. MCP tools for
  the AI agent: `oxee_create_test_campaign`, `oxee_run_test_campaign`,
  `oxee_get_test_execution`, `oxee_compare_test_executions`,
  `oxee_fix_test_call`…

## 0.8.1 — 2026-10-01

- Click the version in the sidebar: release notes of the running version and,
  when GitHub has a newer OxeePhone release, an "Update" badge with its notes
  and the update command (checked by the server, `OXEE_UPDATE_CHECK`).
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
