"""OxeePhone routing tab: graph structure exposed for a call."""

from api.brand.routing import _graph


def test_graph_exposes_structure_and_tool_names_but_no_prompts():
    graph = _graph(
        4,
        {
            "workflow_id": 3,
            "workflow_name": "Cabinet Martin",
            "workflow_json": {
                "nodes": [
                    {
                        "id": "1",
                        "type": "startCall",
                        "position": {"x": 1, "y": 2},
                        "data": {
                            "name": "Accueil",
                            "prompt": "SECRET PROMPT",
                            "tool_uuids": ["t"],
                        },
                    },
                    {
                        "id": 2,
                        "type": "endCall",
                        "data": {"name": "Fin", "prompt": "x"},
                    },
                ],
                "edges": [
                    {
                        "id": "e1",
                        "source": "1",
                        "target": 2,
                        "data": {
                            "label": "Rendez-vous confirmé",
                            "condition": "Le RDV est pris.",
                            "transition_speech": "C'est noté.",
                        },
                    },
                ],
            },
        },
    )
    assert graph["nodes"] == [
        {
            "id": "1",
            "type": "startCall",
            "name": "Accueil",
            "position": {"x": 1, "y": 2},
        },
        {"id": "2", "type": "endCall", "name": "Fin", "position": {"x": 0, "y": 0}},
    ]
    edge = graph["edges"][0]
    assert edge["tool_name"] == "rendez_vous_confirm_"  # what the LLM calls
    assert (edge["source"], edge["target"], edge["condition"]) == (
        "1",
        "2",
        "Le RDV est pris.",
    )
    assert "SECRET PROMPT" not in str(graph)
