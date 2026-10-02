"""OxeePhone test campaign tools on the MCP server (see mcp_tools.py).

    oxee_create_test_campaign → oxee_get_test_campaign (scenarios written in
    the background) → oxee_run_test_campaign (version "published") → poll
    oxee_get_test_execution → change the draft (fixes, versions) →
    oxee_run_test_campaign (version "draft") → oxee_compare_test_executions
    → oxee_fix_test_call for the failed calls.

Executions place real calls (channel "phone") or play as text ("text"); they
run in the background, one at a time.
"""

from __future__ import annotations

from typing import Any, Literal

from api.brand.mcp_tools import _fail, _fix_view, _spawn
from api.mcp_server.auth import authenticate_mcp_request
from api.mcp_server.tracing import traced_tool


def _call_view(call: dict) -> dict:
    judge = call.get("judge") or {}
    return {
        "index": call["index"],
        "pass": call.get("pass"),
        "scenario_id": call["scenario_id"],
        "scenario": (call.get("scenario") or {}).get("title"),
        "status": call.get("status"),
        "verdict": call.get("verdict"),
        "error": call.get("error"),
        "agent_run_id": call.get("agent_run_id"),
        "summary": judge.get("summary"),
        "failed_criteria": [
            c["text"] for c in judge.get("criteria") or [] if not c["pass"]
        ],
        "violated": [f["text"] for f in judge.get("forbidden") or [] if f["violated"]],
        "failed_checks": [
            c["label"] for c in call.get("checks") or [] if not c["pass"]
        ],
        "issues": judge.get("issues"),
        "scenario_issue": judge.get("scenario_issue"),
        "failure_node": judge.get("failure_node"),
        "fix_id": call.get("fix_id"),
    }


@traced_tool
async def oxee_list_test_campaigns() -> list[dict]:
    """Test campaigns with their agent, scenario count and last result."""
    from api.brand import test_campaigns as campaigns
    from api.brand import test_runs as runs
    from api.brand.test_routes import _campaign_summary

    user = await authenticate_mcp_request()
    org = user.selected_organization_id
    executions = await runs.list_executions(org)
    return [
        _campaign_summary(c, executions) for c in await campaigns.list_campaigns(org)
    ]


@traced_tool
async def oxee_create_test_campaign(
    workflow_id: int,
    count: int = 20,
    name: str = "",
    language: str = "French",
    tools_mode: Literal["simulated", "real", "real_with_header"] = "simulated",
    ranges: dict[str, list[int]] | None = None,
    speed: list[float] | None = None,
    max_duration_seconds: int = 300,
    instructions: str | None = None,
) -> dict:
    """Create a test campaign for an agent: ``count`` scenarios (one simulated
    caller each) written by the analysis model in the background. ``ranges``
    sets each caller setting as [min, max] from 1 (easy) to 5 (hard):
    vocabulary, mood, clarity, complexity, depth, impatience, dictation, traps.
    ``speed`` is the caller's voice speed range, e.g. [0.95, 1.15]."""
    from api.brand import test_campaigns as campaigns

    user = await authenticate_mcp_request()
    org = user.selected_organization_id
    try:
        campaign = await campaigns.create(
            org,
            user,
            name=name,
            workflow_id=workflow_id,
            ranges=ranges,
            speed=speed,
            count=count,
            language=language,
            tools_mode=tools_mode,
            max_duration_seconds=max_duration_seconds,
            instructions=instructions,
        )
    except campaigns.CampaignError as e:
        _fail(e)
    _spawn(campaigns.generate(org, campaign["id"]))
    return {"campaign_id": campaign["id"], "status": campaign["status"]}


@traced_tool
async def oxee_get_test_campaign(
    campaign_id: str, include_scenarios: bool = True
) -> dict:
    """A test campaign: settings, executions and (optionally) its scenarios."""
    from api.brand import test_campaigns as campaigns
    from api.brand import test_runs as runs
    from api.brand.test_routes import _execution_summary

    user = await authenticate_mcp_request()
    org = user.selected_organization_id
    campaign = await campaigns.get(org, campaign_id)
    if campaign is None:
        _fail(LookupError("test campaign not found"), 404)
    view = {k: v for k, v in campaign.items() if k != "scenarios"}
    view["executions"] = [
        _execution_summary(runs.stale(e))
        for e in await runs.list_executions(org, campaign_id=campaign_id)
    ]
    if include_scenarios:
        view["scenarios"] = campaign["scenarios"]
    return view


@traced_tool
async def oxee_update_test_scenario(
    campaign_id: str, scenario_id: str, changes: dict[str, Any]
) -> dict:
    """Edit a scenario: title, goal, behaviour, persona, facts, criteria,
    forbidden, expected_end_node, expected_variables, expected_tools,
    tool_hints, levels, speed, voice, caller_number, enabled."""
    from api.brand import test_campaigns as campaigns

    user = await authenticate_mcp_request()
    org = user.selected_organization_id
    campaign = await campaigns.get(org, campaign_id)
    if campaign is None:
        _fail(LookupError("test campaign not found"), 404)
    try:
        scenario = campaigns.update_scenario(campaign, scenario_id, changes)
    except (LookupError, TypeError, ValueError) as e:
        _fail(e)
    await campaigns.save(org, campaign)
    return scenario


@traced_tool
async def oxee_run_test_campaign(
    campaign_id: str,
    version: str = "published",
    channel: Literal["phone", "text"] = "phone",
    passes: int = 1,
    personas: Literal["frozen", "fresh"] = "frozen",
    concurrency: int | None = None,
) -> dict:
    """Play a campaign on a version of its agent: "published", "draft" or a
    version id. "phone" places real calls; "text" plays the conversations as
    text (no telephony, no latency). Poll oxee_get_test_execution."""
    from api.brand import test_campaigns as campaigns
    from api.brand import test_runs as runs

    user = await authenticate_mcp_request()
    org = user.selected_organization_id
    campaign = await campaigns.get(org, campaign_id)
    if campaign is None:
        _fail(LookupError("test campaign not found"), 404)
    try:
        execution = await runs.create_execution(
            org,
            user,
            campaign,
            version=int(version) if str(version).isdigit() else version,
            channel=channel,
            passes=passes,
            personas=personas,
            concurrency=concurrency,
        )
    except runs.ExecutionError as e:
        _fail(e)
    _spawn(runs.run(org, execution["id"], user.id))
    return {"execution_id": execution["id"], "calls": len(execution["calls"])}


@traced_tool
async def oxee_get_test_execution(
    execution_id: str, calls: Literal["failed", "all", "none"] = "failed"
) -> dict:
    """Progress and report of an execution; ``calls`` lists the failed (or
    all) calls with what failed and why."""
    from api.brand import test_runs as runs

    user = await authenticate_mcp_request()
    execution = await runs.get(user.selected_organization_id, execution_id)
    if execution is None:
        _fail(LookupError("test execution not found"), 404)
    execution = runs.stale(execution)
    view = {k: v for k, v in execution.items() if k != "calls"}
    items = execution["calls"]
    view["progress"] = {
        "total": len(items),
        "finished": sum(
            1 for c in items if c.get("status") in ("done", "error", "cancelled")
        ),
    }
    if calls != "none":
        view["calls"] = [
            _call_view(c)
            for c in items
            if calls == "all"
            or c.get("verdict") in ("fail", "partial")
            or c.get("status") == "error"
        ]
    return view


@traced_tool
async def oxee_compare_test_executions(a: str, b: str) -> dict:
    """Execution ``b`` against ``a``: indicators, scenarios improved or
    regressed, coverage, and the agent's configuration diff."""
    from api.brand import test_runs as runs

    user = await authenticate_mcp_request()
    try:
        result = await runs.compare(user.selected_organization_id, a, b)
    except LookupError as e:
        _fail(e, 404)
    diff = result.pop("version_diff", None)
    result["version_changes"] = (diff or {}).get("bullets")
    return result


@traced_tool
async def oxee_cancel_test_execution(execution_id: str) -> dict:
    """Stop an execution: no new call starts, calls in progress finish."""
    from api.brand import test_runs as runs

    await authenticate_mcp_request()
    runs.cancel(execution_id)
    return {"execution_id": execution_id, "cancelling": True}


@traced_tool
async def oxee_fix_test_call(
    execution_id: str, call_index: int, language: str = "English"
) -> dict:
    """Propose an automatic fix for a failed test call (then follow the usual
    fix tools: oxee_get_fix, oxee_apply_fix, oxee_simulate_fix...)."""
    from api.brand import fixes
    from api.brand import test_runs as runs

    user = await authenticate_mcp_request()
    org = user.selected_organization_id
    execution = await runs.get(org, execution_id)
    if execution is None:
        _fail(LookupError("test execution not found"), 404)
    call = next((c for c in execution["calls"] if c["index"] == call_index), None)
    if call is None or call.get("verdict") not in ("fail", "partial"):
        _fail(ValueError("only a failed call can be fixed"))
    fix = await fixes.create(
        org,
        user,
        {"id": f"test:{execution_id}", "workflow_id": execution["workflow_id"]},
        runs.finding_from_call(execution, call),
        language=language,
    )
    call["fix_id"] = fix["id"]
    await runs.save(org, execution)
    if fix["status"] == "proposing":
        _spawn(fixes.propose(org, fix["id"]))
    return _fix_view(fix)


READ_TOOLS = (
    oxee_list_test_campaigns,
    oxee_get_test_campaign,
    oxee_get_test_execution,
    oxee_compare_test_executions,
)
WRITE_TOOLS = (
    oxee_create_test_campaign,
    oxee_update_test_scenario,
    oxee_run_test_campaign,
    oxee_cancel_test_execution,
    oxee_fix_test_call,
)
