"""Agent routing data for the call-detail page.

The run's logs already say *when* the call moved between nodes and which
transition tool the LLM called; this module supplies the graphs those tools
come from (each out-edge is exposed to the LLM as a tool named after the edge
label, described by its condition), for the definition the run used and for
any agent it was handed off to. Only structure is returned: node names, types
and positions, edge labels and conditions — never prompts or tool configs.
"""

from typing import Any

from api.brand.db import get_definition_graphs
from api.services.workflow.workflow_graph import transition_tool_name


def _graph(definition_id: int, entry: dict) -> dict[str, Any]:
    workflow_json = entry.get("workflow_json") or {}
    nodes = []
    for node in workflow_json.get("nodes") or []:
        data = node.get("data") or {}
        nodes.append(
            {
                "id": str(node.get("id")),
                "type": node.get("type"),
                "name": data.get("name") or str(node.get("id")),
                "position": node.get("position") or {"x": 0, "y": 0},
            }
        )
    edges = []
    for edge in workflow_json.get("edges") or []:
        data = edge.get("data") or {}
        label = data.get("label") or ""
        edges.append(
            {
                "id": str(edge.get("id")),
                "source": str(edge.get("source")),
                "target": str(edge.get("target")),
                "label": label,
                "condition": data.get("condition") or "",
                "tool_name": transition_tool_name(label) if label else "",
                "transition_speech": data.get("transition_speech") or None,
            }
        )
    return {
        "definition_id": definition_id,
        "workflow_id": entry.get("workflow_id"),
        "workflow_name": entry.get("workflow_name"),
        "nodes": nodes,
        "edges": edges,
    }


async def run_routing_graphs(run: Any, *, organization_id: int) -> dict[str, Any]:
    """Graphs for the run's definition and every agent visited in the call."""
    visits = (run.gathered_context or {}).get("agent_visits") or []
    visit_ids = [v.get("definition_id") for v in visits if isinstance(v, dict)]
    definitions = await get_definition_graphs(
        [run.definition_id, *visit_ids], organization_id=organization_id
    )
    return {
        "primary_definition_id": run.definition_id,
        "graphs": [
            _graph(definition_id, entry)
            for definition_id, entry in sorted(definitions.items())
        ],
    }
