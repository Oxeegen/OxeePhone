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
