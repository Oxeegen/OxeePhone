"""OxeePhone tools on the MCP server (/api/v1/mcp): analysis, automatic fixes,
versions, test campaigns (mcp_test_tools.py). Lets an AI agent (e.g. Claude Code on the same VM) run the
improvement loop with an organization API key:

    oxee_run_analysis → oxee_get_analysis_report → oxee_propose_fix(es)
    → oxee_get_fix → oxee_apply_fix → oxee_simulate_fix → oxee_get_fix
    → (human publishes, or oxee_publish_draft when allowed)
    → oxee_fix_follow_up → (oxee_rollback_fix when allowed)

Proposals, simulations and analyses run in the background: poll the matching
``get`` tool. Publishing and rolling back change what callers hear, so those
two tools only exist when ``OXEE_MCP_CAN_PUBLISH=true``.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import HTTPException
from mcp.types import ToolAnnotations

from api.mcp_server.auth import authenticate_mcp_request
from api.mcp_server.tracing import traced_tool

CAN_PUBLISH = os.getenv("OXEE_MCP_CAN_PUBLISH", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

_background: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


def _fail(e: Exception, status: int = 422):
    raise HTTPException(status_code=status, detail=str(e)) from e


def _fix_view(fix: dict, *, full: bool = False) -> dict:
    """What an agent needs to decide the next step (no bulky transcripts)."""
    keep = (
        "id",
        "status",
        "report_id",
        "workflow_id",
        "workflow_name",
        "base_version_number",
        "draft_version_number",
        "combined_with",
        "reason",
        "error",
        "review_reason",
        "follow_up",
        "rolled_back_to",
        "created_at",
        "updated_at",
    )
    view = {k: fix.get(k) for k in keep if fix.get(k) is not None}
    view["finding"] = {
        k: fix["finding"].get(k) for k in ("id", "rule", "title", "agent", "node")
    }
    if fix.get("proposal"):
        p = fix["proposal"]
        view["proposal"] = {
            k: p.get(k)
            for k in ("summary", "rationale", "expected_effect", "risks", "test_focus")
        }
        if full:
            view["proposal"]["operations"] = p.get("operations")
    sim = fix.get("simulation")
    if sim:
        view["simulation"] = {
            "status": sim.get("status"),
            "verdict": sim.get("verdict"),
            "summary": sim.get("summary"),
            "error": sim.get("error") or sim.get("judge_error"),
            "cases": [
                {
                    "case": c.get("case"),
                    "source_call": c.get("source_call"),
                    "verdict": c.get("verdict"),
                    "notes": c.get("notes"),
                    "real_path": c.get("original_path"),
                    "published_path": (c.get("baseline") or {}).get("path"),
                    "draft_path": (c.get("candidate") or {}).get("path"),
                    "published_metrics": (c.get("baseline") or {}).get("metrics"),
                    "draft_metrics": (c.get("candidate") or {}).get("metrics"),
                }
                for c in sim.get("cases") or []
            ],
        }
    if full and fix.get("preview"):
        view["changes"] = fix["preview"].get("bullets")
    return view


# --- Agents and versions ------------------------------------------------------


@traced_tool
async def oxee_list_agents() -> list[dict]:
    """List the agents with their published version, draft in progress,
    last run date and number of runs (fix simulations excluded)."""
    from api.brand.db import agent_list_info
    from api.db import db_client

    user = await authenticate_mcp_request()
    org = user.selected_organization_id
    info = await agent_list_info(org)
    workflows = await db_client.get_all_workflows_for_listing(
        organization_id=org, status="active"
    )
    return [
        {
            "id": w.id,
            "name": w.name,
            **{
                k: (v.isoformat() if hasattr(v, "isoformat") else v)
                for k, v in info.get(w.id, {}).items()
            },
        }
        for w in workflows
    ]


@traced_tool
async def oxee_list_versions(workflow_id: int, limit: int = 20) -> dict:
    """Versions of an agent, newest first: status, origin (editor / api / mcp /
    restore / fix), authors, number of calls and a short summary of changes."""
    from api.brand.versions import list_versions
    from api.db import db_client

    user = await authenticate_mcp_request()
    if (
        await db_client.get_workflow(
            workflow_id, organization_id=user.selected_organization_id
        )
        is None
    ):
        _fail(LookupError("agent not found"), 404)
    return await list_versions(
        workflow_id,
        organization_id=user.selected_organization_id,
        limit=min(limit, 100),
    )


@traced_tool
async def oxee_version_diff(
    workflow_id: int, version_id: int, base_version_id: int | None = None
) -> dict:
    """Detailed changes of a version (``version_id`` is the version's id from
    oxee_list_versions) against the previous one or ``base_version_id``."""
    from api.brand.versions import version_diff
    from api.db import db_client

    user = await authenticate_mcp_request()
    if (
        await db_client.get_workflow(
            workflow_id, organization_id=user.selected_organization_id
        )
        is None
    ):
        _fail(LookupError("agent not found"), 404)
    diff = await version_diff(
        workflow_id,
        version_id,
        organization_id=user.selected_organization_id,
        base_id=base_version_id,
    )
    if diff is None:
        _fail(LookupError("version not found"), 404)
    return diff


@traced_tool
async def oxee_restore_version(
    workflow_id: int, version_id: int, replace_draft: bool = False
) -> dict:
    """Create a DRAFT with the content of an earlier version (the published
    version keeps answering calls). Fails when a draft exists unless
    ``replace_draft``."""
    from api.brand import versions
    from api.db import db_client

    user = await authenticate_mcp_request()
    org = user.selected_organization_id
    if await db_client.get_workflow(workflow_id, organization_id=org) is None:
        _fail(LookupError("agent not found"), 404)
    try:
        draft = await versions.restore(
            workflow_id,
            version_id,
            user,
            organization_id=org,
            replace_draft=replace_draft,
        )
    except versions.DraftExists as e:
        _fail(
            ValueError(
                f"draft v{e.draft.version_number} exists; pass replace_draft=true to discard it"
            ),
            409,
        )
    except (LookupError, ValueError) as e:
        _fail(e)
    return {
        "id": draft.id,
        "version_number": draft.version_number,
        "status": draft.status,
    }


# --- Analysis -----------------------------------------------------------------


@traced_tool
async def oxee_run_analysis(
    days: int = 7,
    workflow_id: int | None = None,
    date: str | None = None,
    timezone: str = "UTC",
    language: str = "English",
) -> dict:
    """Start a configuration analysis of the recorded calls (last ``days``
    days: 1, 7 or 30, ending ``date`` YYYY-MM-DD, default today; one agent or
    all). Runs in the background: poll oxee_get_analysis_report."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from api.brand.analysis import create_report, run_analysis

    user = await authenticate_mcp_request()
    try:
        day = date or datetime.now(ZoneInfo(timezone)).strftime("%Y-%m-%d")
        report, kwargs = await create_report(
            user,
            date=day,
            days=days,
            timezone=timezone,
            workflow_id=workflow_id,
            language=language,
        )
    except Exception as e:
        _fail(e)
    _spawn(run_analysis(report["id"], **kwargs))
    return {"report_id": report["id"], "status": report["status"]}


@traced_tool
async def oxee_list_analysis_reports(limit: int = 10) -> list[dict]:
    """Latest analysis reports: id, date, status, number of findings."""
    from api.brand.analysis import REPORT_PREFIX
    from api.brand.db import list_configurations_by_prefix

    user = await authenticate_mcp_request()
    reports = await list_configurations_by_prefix(
        user.selected_organization_id, REPORT_PREFIX, limit=min(limit, 30)
    )
    return [
        {
            "report_id": r["id"],
            "created_at": r.get("created_at"),
            "status": r.get("status"),
            "params": r.get("params"),
            "findings": len(r.get("findings") or []),
        }
        for r in reports
    ]


@traced_tool
async def oxee_get_analysis_report(report_id: str) -> dict:
    """An analysis report: status (running / reviewing / done / failed),
    summary, and findings with whether each can be fixed automatically."""
    from api.brand.analysis import get_report
    from api.brand.fixes import fixability

    user = await authenticate_mcp_request()
    report = await get_report(user.selected_organization_id, report_id)
    if report is None:
        _fail(LookupError("report not found"), 404)
    return {
        "report_id": report["id"],
        "status": report.get("status"),
        "calls_analyzed": report.get("calls_analyzed"),
        "summary": report.get("summary"),
        "error": report.get("error") or report.get("model_error"),
        "findings": [
            {
                **{
                    k: f.get(k)
                    for k in (
                        "id",
                        "severity",
                        "category",
                        "rule",
                        "title",
                        "detail",
                        "recommendation",
                        "agent",
                        "node",
                        "calls",
                    )
                },
                "auto_fixable": fixability(f)["fixable"],
                "not_fixable_reason": (
                    None if fixability(f)["fixable"] else fixability(f)["reason"]
                ),
            }
            for f in report.get("findings") or []
        ],
    }


# --- Fixes --------------------------------------------------------------------


@traced_tool
async def oxee_propose_fixes(
    report_id: str, finding_id: str | None = None, language: str = "English"
) -> list[dict]:
    """Ask the analysis model for a fix of one finding, or of every fixable
    finding of the report without a live fix. Runs in the background: poll
    oxee_get_fix until status is proposed / not_fixable / failed."""
    from api.brand import fixes
    from api.brand.analysis import get_report

    user = await authenticate_mcp_request()
    org = user.selected_organization_id
    report = await get_report(org, report_id)
    if report is None:
        _fail(LookupError("report not found"), 404)
    live = {
        f["finding"].get("id"): f
        for f in await fixes.list_fixes(org, report_id=report_id)
        if f.get("status") in fixes.ACTIVE
    }
    findings = report.get("findings") or []
    if finding_id:
        findings = [f for f in findings if f.get("id") == finding_id]
        if not findings:
            _fail(LookupError("finding not found"), 404)
        if finding_id in live:
            return [_fix_view(live[finding_id])]
    else:
        findings = [
            f
            for f in findings
            if f.get("id") not in live and fixes.fixability(f)["fixable"]
        ]
    created = [
        await fixes.create(org, user, report, f, language=language) for f in findings
    ]

    async def propose_all(ids):
        for fix_id in ids:
            await fixes.propose(org, fix_id)

    _spawn(propose_all([f["id"] for f in created if f["status"] == "proposing"]))
    return [_fix_view(f) for f in created]


@traced_tool
async def oxee_list_fixes(
    report_id: str | None = None,
    workflow_id: int | None = None,
    status: str | None = None,
) -> list[dict]:
    """Automatic fixes, newest first (filter by report, agent or status:
    proposing, proposed, applied, testing, tested, published, rolled_back,
    discarded, failed, not_fixable)."""
    from api.brand.fixes import list_fixes

    user = await authenticate_mcp_request()
    items = await list_fixes(
        user.selected_organization_id, report_id=report_id, workflow_id=workflow_id
    )
    return [_fix_view(f) for f in items if not status or f.get("status") == status]


@traced_tool
async def oxee_get_fix(fix_id: str) -> dict:
    """One fix: proposal (summary, rationale, risks, operations), changes
    against the published version, simulation verdict per case, follow-up."""
    from api.brand import fixes

    user = await authenticate_mcp_request()
    fix = await fixes.get(user.selected_organization_id, fix_id)
    if fix is None:
        _fail(LookupError("fix not found"), 404)
    try:
        fix["preview"] = await fixes.preview_diff(user.selected_organization_id, fix)
    except fixes.FixError:
        fix["preview"] = None
    return _fix_view(fix, full=True)


@traced_tool
async def oxee_apply_fix(fix_id: str, replace_draft: bool = False) -> dict:
    """Save a proposed fix as a DRAFT of the agent (combined with other fixes
    already in a fix draft). The published version is untouched. Fails when a
    draft made by hand exists, unless ``replace_draft``."""
    from api.brand import fixes, versions

    user = await authenticate_mcp_request()
    try:
        return _fix_view(
            await fixes.apply(
                user.selected_organization_id, fix_id, user, replace_draft=replace_draft
            )
        )
    except versions.DraftExists as e:
        _fail(
            ValueError(
                f"draft v{e.draft.version_number} was made by hand; pass replace_draft=true to discard it"
            ),
            409,
        )
    except (LookupError, fixes.FixError) as e:
        _fail(e)


@traced_tool
async def oxee_simulate_fix(fix_id: str, max_cases: int = 3) -> dict:
    """Test an applied fix: the finding's calls are replayed as text on the
    published version and on the draft (tools are not executed), then judged.
    Runs in the background (about a minute per case): poll oxee_get_fix until
    status is tested; read simulation.verdict (pass / mixed / fail /
    inconclusive)."""
    from api.brand import fixes

    user = await authenticate_mcp_request()
    org = user.selected_organization_id
    fix = await fixes.get(org, fix_id)
    if fix is None:
        _fail(LookupError("fix not found"), 404)
    if fix["status"] not in ("applied", "tested"):
        _fail(ValueError(f"fix is {fix['status']}: apply it first"), 409)
    fix.update(status="testing", simulation={"status": "starting", "cases": []})
    await fixes.save(org, fix)
    _spawn(fixes.simulate(org, fix_id, user.id, max_cases=max(1, min(max_cases, 5))))
    return _fix_view(fix)


@traced_tool
async def oxee_discard_fix(fix_id: str) -> dict:
    """Drop a fix (and its draft when the draft holds no other fix)."""
    from api.brand import fixes

    user = await authenticate_mcp_request()
    try:
        return _fix_view(await fixes.discard(user.selected_organization_id, fix_id))
    except (LookupError, fixes.FixError) as e:
        _fail(e, 409)


@traced_tool
async def oxee_fix_follow_up(fix_id: str) -> dict:
    """After publication: is the finding gone from the real calls on the fixed
    version? waiting (not enough calls yet) / fixed / still_present / worse /
    manual (model finding: run a new analysis)."""
    from api.brand import fixes

    user = await authenticate_mcp_request()
    try:
        return await fixes.follow_up(user.selected_organization_id, fix_id)
    except (LookupError, fixes.FixError) as e:
        _fail(e, 409)


# --- Publishing (only with OXEE_MCP_CAN_PUBLISH=true) -------------------------------


@traced_tool
async def oxee_publish_draft(workflow_id: int) -> dict:
    """Publish the agent's draft: new calls use it. Same validation as the
    editor's Publish button. Only publish a draft whose fixes passed their
    simulation, and check the follow-up afterwards."""
    from api.routes.workflow import publish_workflow

    user = await authenticate_mcp_request()
    return await publish_workflow(workflow_id, user=user)


@traced_tool
async def oxee_rollback_fix(fix_id: str, replace_draft: bool = False) -> dict:
    """Put back in production the version a published fix replaced (as a new
    version). Every fix of that version is undone with it."""
    from api.brand import fixes, versions

    user = await authenticate_mcp_request()
    try:
        return _fix_view(
            await fixes.rollback(
                user.selected_organization_id, fix_id, user, replace_draft=replace_draft
            )
        )
    except versions.DraftExists as e:
        _fail(
            ValueError(
                f"draft v{e.draft.version_number} exists; pass replace_draft=true to discard it"
            ),
            409,
        )
    except (LookupError, fixes.FixError) as e:
        _fail(e, 409)


_READ_ONLY = ToolAnnotations(
    readOnlyHint=True, idempotentHint=True, destructiveHint=False, openWorldHint=False
)
_WRITES = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, openWorldHint=False
)
_PUBLISHES = ToolAnnotations(
    readOnlyHint=False, destructiveHint=True, openWorldHint=False
)

READ_TOOLS = (
    oxee_list_agents,
    oxee_list_versions,
    oxee_version_diff,
    oxee_list_analysis_reports,
    oxee_get_analysis_report,
    oxee_list_fixes,
    oxee_get_fix,
    oxee_fix_follow_up,
)
WRITE_TOOLS = (
    oxee_restore_version,
    oxee_run_analysis,
    oxee_propose_fixes,
    oxee_apply_fix,
    oxee_simulate_fix,
    oxee_discard_fix,
)
PUBLISH_TOOLS = (oxee_publish_draft, oxee_rollback_fix)


def register(mcp: Any) -> None:
    from api.brand.config import BRAND

    reads, writes = list(READ_TOOLS), list(WRITE_TOOLS)
    if BRAND.test_campaigns:
        from api.brand import mcp_test_tools

        reads += mcp_test_tools.READ_TOOLS
        writes += mcp_test_tools.WRITE_TOOLS
    for tool in reads:
        mcp.tool(tool, annotations=_READ_ONLY)
    for tool in writes:
        mcp.tool(tool, annotations=_WRITES)
    if CAN_PUBLISH:
        for tool in PUBLISH_TOOLS:
            mcp.tool(tool, annotations=_PUBLISHES)
