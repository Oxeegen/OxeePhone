<p align="center">
  <img src="/brand/assets/oxeephone-app-icon-256.png" width="96" alt="OxeePhone">
</p>

<h1 align="center">OxeePhone</h1>

<p align="center">
  <b>Oxeegen's self-hosted voice agent platform.</b><br>
  Build phone and web voice agents on your own models, see exactly what happens in every call,<br>
  and let the platform find, fix and test what goes wrong in your agents' configuration.
</p>

<p align="center">
  <a href="https://github.com/Oxeegen/OxeePhone/releases/latest"><img src="https://img.shields.io/github/v/release/Oxeegen/OxeePhone?label=release&color=5E4AF5" alt="Latest release"></a>
  <a href="/LICENSE"><img src="https://img.shields.io/badge/license-BSD%202--Clause-5E4AF5" alt="BSD 2-Clause"></a>
  <img src="https://img.shields.io/badge/self--hosted-Docker-5E4AF5" alt="Self-hosted with Docker">
  <img src="https://img.shields.io/badge/based%20on-Dograh%201.47-5E4AF5" alt="Based on Dograh 1.47">
</p>

<p align="center">
  <img src="/brand/assets/screenshots/call-playback.gif" width="900" alt="Call detail: recording with waveform and synchronised transcript">
</p>

---

## Highlights

- **Your models, your servers.** Every service (LLM, speech-to-text, voice, embeddings) runs on an
  OpenAI-compatible endpoint you host. No call to any third-party platform, no telemetry.
- **A call detail worth the name.** Recording with waveform, transcript synchronised with the audio,
  tool calls, per-stage latency, the path through your agent's nodes and why each move happened.
- **The platform reviews your agents.** An analysis of the recorded calls finds slow replies, silences,
  stalled conversations, routing loops and misrouting, then proposes a fix, tests it by replaying the
  real calls against a draft, and follows it up once published.
- **Made to be driven by an AI agent.** Analysis, fixes, simulations and versions are MCP tools and REST
  routes, usable with an API key.

## Features

### Build agents

A visual graph of conversation nodes linked by transitions, each with its prompt, tools and knowledge base.

<img src="/brand/assets/screenshots/01-agent-editor.png" alt="Agent editor">

- **Speaking plans** per agent (Vapi-style): how long to wait before answering, smart endpointing,
  silence needed after a sentence / a number / an unfinished phrase, words or voice needed to
  interrupt the agent, back-off after an interruption.
- **Versions**: every version keeps its author and origin (editor, API key, AI agent, restore,
  automatic fix), the number of calls it answered, a plain and an AI-written summary of its changes,
  word-level diffs, and a one-click restore.

<img src="/brand/assets/screenshots/08-versions.png" alt="Agent versions and diffs">

<details>
<summary>Speaking plan settings</summary>

<img src="/brand/assets/screenshots/09-speaking-plan.png" alt="Speaking plans">
</details>

### Self-hosted models

- **Local Models** for every service: base URL, key, and the model picked from the list your endpoint
  serves. Bring your own vLLM, speaches or any OpenAI-compatible server.
- Voice preview, speed, language and volume, **French text normalisation** (numbers, dates, hours)
  and a **pronunciation dictionary**.
- Knowledge base parsed and embedded locally (PDF, DOCX).

### Every call, in detail

- Recording with caller / agent waveforms, speed control, download.
- Transcript synchronised with the audio: the message being played is highlighted, click one to jump to it.
- Tool calls with arguments and results, interruptions, events.
- **Latency** per stage (endpointing, transcription, LLM, tools, first sentence, voice) and per turn.
- **Routing**: the path through the agent's nodes, the condition behind each move and what the caller had just said.

<img src="/brand/assets/screenshots/03-call-latency.png" alt="Latency breakdown">

<img src="/brand/assets/screenshots/routing-graph.gif" alt="Routing graph linked to the steps of the call">

### Reports

Latency (median, p90, by stage, by day), token consumption and cache hit rate, interruptions, call
duration, tool reliability, routing between agents.

<img src="/brand/assets/screenshots/05-reports.png" alt="Reporting insights">

### Configuration analysis and automatic fixes

1. **Analysis**: rules computed on the recorded calls (thresholds proposed by the model, editable),
   reviewed by your analysis model with the transcripts.
2. **Proposal**: for each fixable finding, the model edits prompts, transition conditions or bounded
   settings, never the structure. The change is shown as a diff before anything is saved.
3. **Draft**: the fix is saved as a draft version; the published agent keeps answering calls.
4. **Test**: the real calls of the finding are replayed as text on the published version and on the
   draft (tools are never executed: their recorded results are replayed), compared and judged.
5. **Publish, follow up, roll back**: once published, the same rules check the next real calls; a
   fix that does not work is rolled back in one click.

<img src="/brand/assets/screenshots/06-fix-proposal.png" alt="Automatic fix proposal">

<img src="/brand/assets/screenshots/07-fix-simulation.png" alt="Fix tested by simulation">

### Driven by an AI agent

`oxee_*` tools on the MCP server (`/api/v1/mcp/`) and the same operations in REST: run an analysis,
propose and apply fixes, simulate, follow up, browse and restore versions. Publishing stays a human
decision unless you allow it. See [`brand/agent-vm/`](/brand/agent-vm/README.md).

### Deployment

- **One-command install** on Ubuntu, with generated secrets and free ports.
- **Works under every name of the server** (LAN IP, VPN hostname): UI, API, WebSocket and recordings
  on one origin, HTTPS with a generated certificate (browsers only give the microphone to HTTPS pages).
- **Runs next to an official Dograh** on the same host: every port is configurable, OxeePhone has its
  own TURN server.
- **Update notice** in the app when a new release is out, with its release notes.

## Install

On an Ubuntu 22.04 / 24.04 server (4 vCPU, 8 GB RAM, 20 GB free):

```bash
curl -fsSL https://raw.githubusercontent.com/Oxeegen/OxeePhone/main/brand/install.sh | sudo bash
```

The script installs Docker if needed, gets the latest release into `/opt/oxeephone`, writes `.env`,
builds and starts the stack, and prints the addresses to open. Update later with
`sudo /opt/oxeephone/brand/install.sh update`.

- [Installation, configuration, flags](/brand/README.md)
- [Access from several networks, HTTPS certificate](/brand/proxy/README.md)
- [Driving OxeePhone from an AI agent](/brand/agent-vm/README.md)
- [Changelog](/brand/CHANGELOG.md)

## Based on Dograh

OxeePhone is a fork of [Dograh](https://github.com/dograh-hq/dograh) (BSD 2-Clause, © Zansat
Technologies) by [Oxeegen](https://github.com/Oxeegen). Everything OxeePhone adds lives in a brand
layer (`api/brand`, `ui/src/brand`, `brand/`) behind flags, so upstream releases can still be merged.
Thanks to the Dograh team for the platform this is built on.

License: [BSD 2-Clause](/LICENSE).
