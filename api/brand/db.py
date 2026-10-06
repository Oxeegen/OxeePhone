"""OxeePhone DB access (brand layer).

Kept out of ``api/db`` to avoid touching upstream clients; same conventions:
queries live here, callers stay free of sessions, and every lookup is scoped by
organization through ``WorkflowModel``.
"""

from sqlalchemy import select

from api.db import db_client
from api.db.models import WorkflowDefinitionModel, WorkflowModel


async def get_definition_graphs(
    definition_ids: list[int], *, organization_id: int
) -> dict[int, dict]:
    """Return ``{definition_id: {workflow_id, workflow_name, workflow_json}}``.

    Definitions belonging to another organization are silently omitted.
    """
    ids = sorted({i for i in definition_ids if i is not None})
    if not ids:
        return {}
    async with db_client.async_session() as session:
        result = await session.execute(
            select(
                WorkflowDefinitionModel.id,
                WorkflowDefinitionModel.workflow_json,
                WorkflowModel.id,
                WorkflowModel.name,
            )
            .join(
                WorkflowModel, WorkflowModel.id == WorkflowDefinitionModel.workflow_id
            )
            .where(
                WorkflowDefinitionModel.id.in_(ids),
                WorkflowModel.organization_id == organization_id,
            )
        )
        return {
            definition_id: {
                "workflow_id": workflow_id,
                "workflow_name": workflow_name,
                "workflow_json": workflow_json or {},
            }
            for definition_id, workflow_json, workflow_id, workflow_name in result.all()
        }


INSIGHTS_MAX_RUNS = 5000
# Text replays of automatic-fix tests (api/brand/simulation.py).
SIM_RUN_PREFIX = "OXEE-SIM-"
# Calls of the test campaigns, both sides (api/brand/test_runs.py).
TEST_RUN_PREFIX = "OXEE-TEST-"


def production_runs():
    """Condition leaving out simulations and test-campaign calls."""
    from sqlalchemy import and_

    from api.db.models import WorkflowRunModel

    return and_(
        ~WorkflowRunModel.name.startswith(SIM_RUN_PREFIX),
        ~WorkflowRunModel.name.startswith(TEST_RUN_PREFIX),
    )


async def get_runs_for_insights(
    *,
    organization_id: int,
    start_utc,
    end_utc,
    workflow_id: int | None = None,
    limit: int = INSIGHTS_MAX_RUNS,
) -> list[dict]:
    """Runs of a period with what the reporting insights need (org-scoped).

    Same window and scoping as the daily report (created_at within the local
    day(s), organization through ``WorkflowModel``), newest first, capped.
    """
    from api.db.models import WorkflowRunModel

    async with db_client.async_session() as session:
        query = (
            select(
                WorkflowRunModel.id,
                WorkflowRunModel.workflow_id,
                WorkflowModel.name,
                WorkflowRunModel.definition_id,
                WorkflowRunModel.created_at,
                WorkflowRunModel.is_completed,
                WorkflowRunModel.mode,
                WorkflowRunModel.usage_info,
                WorkflowRunModel.gathered_context,
                WorkflowRunModel.logs,
            )
            .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
            .where(
                WorkflowModel.organization_id == organization_id,
                WorkflowRunModel.created_at >= start_utc,
                WorkflowRunModel.created_at <= end_utc,
                production_runs(),
            )
            .order_by(WorkflowRunModel.created_at.desc())
            .limit(limit)
        )
        if workflow_id is not None:
            query = query.where(WorkflowRunModel.workflow_id == workflow_id)
        rows = (await session.execute(query)).all()
    return [
        {
            "id": r[0],
            "workflow_id": r[1],
            "workflow_name": r[2],
            "definition_id": r[3],
            "created_at": r[4],
            "is_completed": r[5],
            "mode": r[6],
            "usage_info": r[7] or {},
            "gathered_context": r[8] or {},
            "logs": r[9] or {},
        }
        for r in rows
    ]


async def list_configurations_by_prefix(
    organization_id: int, prefix: str, *, limit: int = 50
) -> list[dict]:
    """Values of the organization's configurations whose key starts with ``prefix``
    (newest first)."""
    from api.db.models import OrganizationConfigurationModel

    async with db_client.async_session() as session:
        rows = (
            await session.execute(
                select(OrganizationConfigurationModel.value)
                .where(
                    OrganizationConfigurationModel.organization_id == organization_id,
                    OrganizationConfigurationModel.key.startswith(prefix),
                )
                .order_by(OrganizationConfigurationModel.created_at.desc())
                .limit(limit)
            )
        ).all()
    return [r[0] for r in rows if r[0]]


async def delete_configuration(organization_id: int, key: str) -> bool:
    from sqlalchemy import delete

    from api.db.models import OrganizationConfigurationModel

    async with db_client.async_session() as session:
        result = await session.execute(
            delete(OrganizationConfigurationModel).where(
                OrganizationConfigurationModel.organization_id == organization_id,
                OrganizationConfigurationModel.key == key,
            )
        )
        await session.commit()
        return (result.rowcount or 0) > 0


async def count_runs_by_definition(
    workflow_id: int, *, organization_id: int
) -> dict[int, int]:
    """``{definition_id: number of runs}`` for one workflow (org-scoped)."""
    from sqlalchemy import func

    from api.db.models import WorkflowRunModel

    async with db_client.async_session() as session:
        rows = (
            await session.execute(
                select(WorkflowRunModel.definition_id, func.count(WorkflowRunModel.id))
                .join(WorkflowModel, WorkflowModel.id == WorkflowRunModel.workflow_id)
                .where(
                    WorkflowRunModel.workflow_id == workflow_id,
                    WorkflowModel.organization_id == organization_id,
                    production_runs(),
                )
                .group_by(WorkflowRunModel.definition_id)
            )
        ).all()
    return {d: n for d, n in rows if d is not None}


async def get_workflow_version(
    workflow_id: int, definition_id: int
) -> WorkflowDefinitionModel | None:
    """One version of a workflow (the caller checked the workflow's organization)."""
    async with db_client.async_session() as session:
        return (
            (
                await session.execute(
                    select(WorkflowDefinitionModel).where(
                        WorkflowDefinitionModel.id == definition_id,
                        WorkflowDefinitionModel.workflow_id == workflow_id,
                    )
                )
            )
            .scalars()
            .first()
        )


async def get_previous_version(
    workflow_id: int, version_number: int
) -> WorkflowDefinitionModel | None:
    """The version just before ``version_number`` (any status)."""
    async with db_client.async_session() as session:
        return (
            (
                await session.execute(
                    select(WorkflowDefinitionModel)
                    .where(
                        WorkflowDefinitionModel.workflow_id == workflow_id,
                        WorkflowDefinitionModel.version_number < version_number,
                        WorkflowDefinitionModel.status.in_(
                            ["published", "draft", "archived"]
                        ),
                    )
                    .order_by(WorkflowDefinitionModel.version_number.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )


def _run_columns():
    from api.db.models import WorkflowRunModel

    return (
        WorkflowRunModel.id,
        WorkflowRunModel.workflow_id,
        WorkflowModel.name,
        WorkflowRunModel.definition_id,
        WorkflowRunModel.created_at,
        WorkflowRunModel.is_completed,
        WorkflowRunModel.mode,
        WorkflowRunModel.usage_info,
        WorkflowRunModel.gathered_context,
        WorkflowRunModel.logs,
    )


def _run_dict(r) -> dict:
    return {
        "id": r[0],
        "workflow_id": r[1],
        "workflow_name": r[2],
        "definition_id": r[3],
        "created_at": r[4],
        "is_completed": r[5],
        "mode": r[6],
        "usage_info": r[7] or {},
        "gathered_context": r[8] or {},
        "logs": r[9] or {},
    }


async def get_runs_by_ids(run_ids: list[int], *, organization_id: int) -> list[dict]:
    """Runs by id, same shape as ``get_runs_for_insights`` (org-scoped, in the
    given order)."""
    from api.db.models import WorkflowRunModel

    ids = [int(i) for i in run_ids if i is not None]
    if not ids:
        return []
    async with db_client.async_session() as session:
        rows = (
            await session.execute(
                select(*_run_columns())
                .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                .where(
                    WorkflowRunModel.id.in_(ids),
                    WorkflowModel.organization_id == organization_id,
                )
            )
        ).all()
    by_id = {r[0]: _run_dict(r) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


async def recent_calls(
    workflow_id: int,
    *,
    organization_id: int,
    limit: int = 10,
    definition_id: int | None = None,
) -> list[dict]:
    """Latest completed real calls (no text chats, no simulations) of an agent,
    optionally made on one version."""
    from api.db.models import WorkflowRunModel

    query = (
        select(*_run_columns())
        .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
        .where(
            WorkflowRunModel.workflow_id == workflow_id,
            WorkflowModel.organization_id == organization_id,
            WorkflowRunModel.is_completed.is_(True),
            WorkflowRunModel.mode != "textchat",
            production_runs(),
        )
        .order_by(WorkflowRunModel.created_at.desc())
        .limit(limit)
    )
    if definition_id is not None:
        query = query.where(WorkflowRunModel.definition_id == definition_id)
    async with db_client.async_session() as session:
        rows = (await session.execute(query)).all()
    return [_run_dict(r) for r in rows]


async def find_workflow_by_name(organization_id: int, name: str) -> int | None:
    async with db_client.async_session() as session:
        row = (
            await session.execute(
                select(WorkflowModel.id).where(
                    WorkflowModel.organization_id == organization_id,
                    WorkflowModel.name == name,
                )
            )
        ).first()
    return row[0] if row else None


async def agent_list_info(organization_id: int) -> dict[int, dict]:
    """Per agent: last run (simulations excluded), published and draft version."""
    from sqlalchemy import func

    from api.db.models import WorkflowRunModel

    async with db_client.async_session() as session:
        last_runs = (
            await session.execute(
                select(
                    WorkflowRunModel.workflow_id,
                    func.max(WorkflowRunModel.created_at),
                    func.count(WorkflowRunModel.id),
                )
                .join(WorkflowModel, WorkflowModel.id == WorkflowRunModel.workflow_id)
                .where(
                    WorkflowModel.organization_id == organization_id,
                    production_runs(),
                )
                .group_by(WorkflowRunModel.workflow_id)
            )
        ).all()
        versions = (
            await session.execute(
                select(
                    WorkflowDefinitionModel.workflow_id,
                    WorkflowDefinitionModel.status,
                    WorkflowDefinitionModel.version_number,
                    WorkflowDefinitionModel.published_at,
                )
                .join(
                    WorkflowModel,
                    WorkflowModel.id == WorkflowDefinitionModel.workflow_id,
                )
                .where(
                    WorkflowModel.organization_id == organization_id,
                    WorkflowDefinitionModel.status.in_(["published", "draft"]),
                )
            )
        ).all()
    info: dict[int, dict] = {}
    for workflow_id, last_run_at, runs in last_runs:
        entry = info.setdefault(workflow_id, {})
        entry["last_run_at"] = last_run_at
        entry["runs"] = runs
    for workflow_id, status, number, published_at in versions:
        entry = info.setdefault(workflow_id, {})
        if status == "published":
            entry["published_version"] = number
            entry["published_at"] = published_at
        else:
            entry["draft_version"] = number
    return info


async def find_run_by_name(organization_id: int, name: str) -> dict | None:
    """The newest run with this exact name (org-scoped), shaped like
    ``get_runs_by_ids``."""
    from api.db.models import WorkflowRunModel

    async with db_client.async_session() as session:
        row = (
            await session.execute(
                select(*_run_columns())
                .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                .where(
                    WorkflowModel.organization_id == organization_id,
                    WorkflowRunModel.name == name,
                )
                .order_by(WorkflowRunModel.id.desc())
                .limit(1)
            )
        ).first()
    return _run_dict(row) if row else None


async def delete_test_caller_run(organization_id: int, run_id: int) -> bool:
    """Delete the caller side of a phone test call (the agent side holds the
    conversation). Only a run named as a test caller run, in this
    organization, is deleted; rows that point at it are deleted with it."""
    from sqlalchemy import delete

    from api.db.models import WorkflowRunModel

    async with db_client.async_session() as session:
        owned = select(WorkflowModel.id).where(
            WorkflowModel.organization_id == organization_id
        )
        result = await session.execute(
            delete(WorkflowRunModel).where(
                WorkflowRunModel.id == run_id,
                WorkflowRunModel.workflow_id.in_(owned),
                WorkflowRunModel.name.like(f"{TEST_RUN_PREFIX}%-caller"),
            )
        )
        await session.commit()
    return bool(result.rowcount)


async def agent_phone_numbers(organization_id: int, workflow_id: int) -> list[dict]:
    """Active numbers routing inbound calls to an agent."""
    from api.db.models import TelephonyPhoneNumberModel

    async with db_client.async_session() as session:
        rows = (
            await session.execute(
                select(
                    TelephonyPhoneNumberModel.address,
                    TelephonyPhoneNumberModel.telephony_configuration_id,
                    TelephonyPhoneNumberModel.label,
                )
                .where(
                    TelephonyPhoneNumberModel.organization_id == organization_id,
                    TelephonyPhoneNumberModel.inbound_workflow_id == workflow_id,
                    TelephonyPhoneNumberModel.is_active.is_(True),
                )
                .order_by(TelephonyPhoneNumberModel.id)
            )
        ).all()
    return [
        {"address": a, "telephony_configuration_id": c, "label": label}
        for a, c, label in rows
    ]
