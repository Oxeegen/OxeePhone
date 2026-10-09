# OxeePhone changelog

OxeePhone versions are independent of the Dograh base version
(`ui/package.json`, `api/pyproject.toml`), which follows upstream. The OxeePhone
version lives in `ui/src/brand/brand.ts` and `api/brand/config.py` (a test
keeps them equal).

## 0.9.8 — 2026-10-09

- Test campaigns › Scenarios: the campaign's instructions to the scenario
  writer can be edited. Saving them revises the existing scenarios to follow
  them (in the background, with progress), keeping each scenario's caller
  settings, voice, number and enabled state; scenarios edited by hand can be
  left out. Revised scenarios are marked. Executions already played keep the
  scenarios as they were.
- Test campaigns › Scenarios: the search field can be cleared.
- Test executions: each call has a "Transcript" button opening the call's
  transcript (as in the Transcript tab of the call detail, with tool calls and
  node changes) in a dialog, with the recording player for phone calls.
- Test campaigns, simulated tools: a tool whose own deadline is shorter than
  the simulation needs gets a few seconds more (it used to time out and the
  agent heard a failure); "Transfer to agent" tools are simulated like
  transfers (announcement, then the call ends as transferred; text tests
  refused them); the simulator of MCP tools gets their description and
  parameters.

## 0.9.7 — 2026-10-09

- Test campaigns: transfers are simulated when the campaign's tools are
  (simulated or real with the test header). A "Transfer call" tool connects
  nowhere: its transfer message plays, the destination "answers" and the call
  ends as transferred. An HTTP tool that hands the call over (to the
  switchboard, a department, a number) is recognized by the tool simulator:
  it succeeds and the agent's part of the call ends, as when the PBX takes
  the call. The judge is told the transfer was simulated and completed, so
  the goal and the criteria about putting the caller through count as met;
  an expected end node counts as reached. Shown as "Transferred (simulated)"
  on the call. Before, a text test refused transfers and a phone test placed
  a real one.
- Test campaigns: the start node's pre-call fetch is simulated when the tools
  are: a model playing the caller's CRM answers with the variables the
  agent's texts use ({{name}}), consistent with the scenario's caller. Text
  test calls count as inbound calls, so a fetch set for inbound calls runs
  there too.

## 0.9.6 — 2026-10-09

- Latency: "Reply time" is named "Time to first audio" everywhere (call
  detail, Reports, Analysis, test executions, comparisons, thresholds): the
  delay from the end of the caller's turn to the agent's first audio.
- Voice fluency is timed from the request to the voice model: its first audio
  now includes the connection and the server wait, and matches the Voice
  stage of the latency breakdown; the generation speed counts them too.
- Files: Markdown and text documents open in a preview (Markdown formatted,
  with tables and task lists, or as source); documents kept whole show the
  text extracted from them.
- Tools, Files, Recordings: the search field has a button (and Escape) to
  clear the filter.

## 0.9.5 — 2026-10-08

- Call engine › Performance: "Let the model think before answering", off by
  default. Reasoning models served by Local Models (Oxee-flash and the other
  Qwen3-style models) thought silently before each reply, which added one to
  several seconds before the agent could speak; they now answer at once
  (`chat_template_kwargs.enable_thinking = false`). Turn it on per agent or
  for the platform when a use case needs the reasoning.

- Latency: the reply time no longer counts the end-of-turn wait (voice
  detection silence + speaking plan), a setting of the agent rather than
  processing. The wait is shown apart, greyed, with the time the caller
  actually hears ("heard" / "perceived") next to the reply time: call detail,
  Reports, Analysis, test executions and comparisons. In the technical score
  the wait is no longer a graded post. Default reply thresholds lowered by
  200 ms (1.8 s / 2.8 s); thresholds an organization has set are kept. Older
  test executions are converted when their report is computed again.
- Voice fluency: each sentence spoken by the Local Models voice records its
  time to first audio, total synthesis time, audio length, generation speed
  (seconds of speech per second of synthesis) and the gaps heard when the
  voice runs late. Shown in the call detail (Latency tab), as a graded "Voice
  fluency" post in test executions (thresholds ×1.5 / ×1.1 in Analysis
  settings), compared between executions, and flagged by the Analysis
  ("voice generated barely faster than spoken", "gaps inside sentences").

## 0.9.4 — 2026-10-06

- Call engine › Performance: the first audio chunk defaults to 250 ms instead
  of pipecat's 500 ms (voxee-tts-pro sends its first audio after ~250 ms; the
  agent spoke ~215 ms later than needed on every reply). Still settable per
  platform and per agent; "Restore built-in values" now restores 250 ms.
- Call engine › Performance: "Speak the first clause without waiting for the
  sentence" (off by default). The start of each reply goes to the voice at its
  first comma or colon, after three words, instead of at the end of the first
  sentence.
- Call-engine settings also apply to an agent taking over a call (transfer).
- Recordings › Generate: a recording spoken by the organization's voice model,
  with a chosen voice, speed and text (up to 1,000 characters), with a Listen
  preview. It can become an agent's greeting right away, or later from the
  recording's row; the change goes into a draft and the text greeting stays in
  the start node, ready to be switched back.
- Test executions: each call, each scenario (one link per play) and each
  "scenario to review" links to the agent-side run of the call.
- Phone test calls: the caller side (the test caller's run) is no longer
  kept. Its pipeline saves no logs, recording or transcript and runs no
  post-call work, and the run is deleted once the call is over; the agent
  side holds the conversation. A call that fails to pair keeps its caller run
  for diagnosis.

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
