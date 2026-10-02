# Driving OxeePhone from an AI agent on the VM

OxeePhone exposes its improvement loop (analysis → automatic fixes → test by
simulation → publication → follow-up) to an external agent, through the MCP
server (`/api/v1/mcp/`) or the REST API (`/api/v1/oxee/*`). Both authenticate
with an organization **API key**.

## 1. API key

In OxeePhone: **Developers › API keys › Create**. Create one key per agent (e.g.
`agent-vm`): every version it changes is labelled with its prefix
(`API key dgr_xxxx…` / `MCP agent`) on the versions page, and revoking it
cuts the agent off immediately.

The key acts with the rights of the user who created it. What the agent may do
is set on the API side:

| Variable (API container) | Default | Effect |
|---|---|---|
| `OXEE_AGENT_FIXES` | `true` | Analysis / fix / version MCP tools |
| `OXEE_MCP_CAN_PUBLISH` | *(unset: false)* | Adds `oxee_publish_draft` and `oxee_rollback_fix`. Without it the agent prepares, tests and documents fixes; a human publishes them from the Analysis or versions page |

## 2. Claude Code on the VM

```bash
export OXEEPHONE_API_KEY=dgr_...   # keep it out of shell history / git
claude mcp add --transport http oxeephone http://localhost:8000/api/v1/mcp/ \
  --header "X-API-Key: $OXEEPHONE_API_KEY"
claude mcp list
```

Interactive: ask *"Run an analysis of the last 7 days and fix what can be
fixed"*. Unattended (cron or systemd timer, e.g. every night):

```bash
claude -p "$(cat /opt/oxeephone/brand/agent-vm/improve-agents.md)" \
  --allowedTools "mcp__oxeephone" --output-format text \
  >> /var/log/oxeephone-agent.log 2>&1
```

`improve-agents.md` (next to this file) is the reference loop; adapt it
(language, which agents, when to stop).

## 3. MCP tools

| Tool | What it does |
|---|---|
| `oxee_list_agents` | Agents, published version, draft in progress, last run, number of runs |
| `oxee_run_analysis` → `oxee_get_analysis_report` | Analysis of the recorded calls (background; poll the report) |
| `oxee_list_analysis_reports` | Latest reports |
| `oxee_propose_fixes` → `oxee_get_fix` | Fix proposals by the analysis model, for one finding or all fixable ones (background) |
| `oxee_apply_fix` | Saves a proposal as a **draft** (published version untouched) |
| `oxee_simulate_fix` → `oxee_get_fix` | Replays the finding's calls on the published version and the draft; verdict pass / mixed / fail / inconclusive |
| `oxee_discard_fix` | Drops a fix and its draft |
| `oxee_fix_follow_up` | After publication: fixed / still present / worse on real calls |
| `oxee_list_versions`, `oxee_version_diff`, `oxee_restore_version` | Versions, detailed changes, restore as draft |
| `oxee_create_test_campaign` → `oxee_get_test_campaign` | Test campaign for an agent: scenarios written in the background (caller settings as [min, max] ranges) |
| `oxee_update_test_scenario` | Edit a scenario (goal, facts, criteria, levels, voice, number, enabled…) |
| `oxee_run_test_campaign` → `oxee_get_test_execution` | Play the campaign on `published`, `draft` or a version id, by `phone` or as `text` (background); the execution lists the failed calls and why |
| `oxee_compare_test_executions` | Execution B against A: indicators, scenarios improved / regressed, configuration diff |
| `oxee_fix_test_call` | Automatic fix of a failed test call (then the fix tools above) |
| `oxee_cancel_test_execution`, `oxee_list_test_campaigns` | |
| `oxee_publish_draft`, `oxee_rollback_fix` | Only with `OXEE_MCP_CAN_PUBLISH=true` |

Upstream Dograh tools (`list_workflows`, `get_workflow_code`,
`save_workflow`…) stay available; drafts saved with `save_workflow` are
labelled `MCP agent` too.

## 4. Same thing in REST

```bash
H="X-API-Key: $OXEEPHONE_API_KEY"; B=http://localhost:8000/api/v1
curl -s -X POST $B/oxee/analysis/reports -H "$H" -H 'Content-Type: application/json' \
  -d '{"date":"2026-10-01","timezone":"Europe/Paris","days":7,"language":"French"}'
curl -s $B/oxee/analysis/reports/<report_id> -H "$H"
curl -s -X POST $B/oxee/fixes -H "$H" -H 'Content-Type: application/json' \
  -d '{"report_id":"<report_id>","language":"French"}'          # every fixable finding
curl -s $B/oxee/fixes/<fix_id> -H "$H"
curl -s -X POST $B/oxee/fixes/<fix_id>/apply -H "$H" -H 'Content-Type: application/json' -d '{}'
curl -s -X POST $B/oxee/fixes/<fix_id>/simulate -H "$H" -H 'Content-Type: application/json' -d '{}'
curl -s -X POST $B/workflow/<agent_id>/publish -H "$H"            # human decision
curl -s -X POST $B/oxee/fixes/<fix_id>/follow-up -H "$H"
curl -s -X POST $B/oxee/fixes/<fix_id>/rollback -H "$H" -H 'Content-Type: application/json' -d '{}'
```

Every route is described in the OpenAPI schema (`/api/v1/openapi.json`, tag
`oxeephone`).

## Safety notes

- Fixes only edit existing prompts, greetings, transition conditions and
  bounded settings; they never add or remove nodes, tools or documents.
- Simulations never execute tools (recorded results are replayed) and never
  trigger post-call webhooks. Simulation runs are named `OXEE-SIM-…`.
- A draft made by hand is never replaced without `replace_draft=true`.
- One simulation runs at a time; the Oxeegen gateway rate-limits bursts.
