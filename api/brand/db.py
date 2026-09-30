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
