"""OxeePhone: agent versions (diff, origin tracking, restore)."""

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.brand import versions
from api.brand.version_diff import diff_versions, word_diff

BASE = {
    "workflow_json": {
        "nodes": [
            {
                "id": "1",
                "type": "startCall",
                "position": {"x": 0, "y": 0},
                "data": {
                    "name": "Accueil",
                    "prompt": "Tu es l'accueil du cabinet du docteur Martin. Réponses courtes : 1 à 2 phrases. Identifie le besoin du patient.",
                    "allow_interrupt": True,
                },
            },
            {
                "id": "2",
                "type": "agentNode",
                "position": {"x": 0, "y": 200},
                "data": {"name": "Urgences", "prompt": "Oriente vers le 15."},
            },
        ],
        "edges": [
            {
                "id": "e1-2",
                "source": "1",
                "target": "2",
                "data": {
                    "label": "Urgence",
                    "condition": "Le patient décrit une urgence.",
                },
            },
        ],
    },
    "workflow_configurations": {
        "max_user_idle_timeout": 10,
        "speaking_plan": {"start": {"wait_seconds": 0.4}, "stop": {"num_words": 0}},
    },
    "template_context_variables": {},
}


def _changed():
    v = copy.deepcopy(BASE)
    nodes = v["workflow_json"]["nodes"]
    nodes[0]["data"]["prompt"] = nodes[0]["data"]["prompt"].replace(
        "1 à 2 phrases", "une phrase"
    )
    nodes[0]["data"]["allow_interrupt"] = False
    nodes.append(
        {
            "id": "3",
            "type": "endCall",
            "position": {"x": 0, "y": 400},
            "data": {"name": "Fin", "prompt": "Au revoir."},
        }
    )
    v["workflow_json"]["edges"][0]["data"][
        "condition"
    ] = "Douleur thoracique, malaise, saignement."
    v["workflow_json"]["edges"].append(
        {"id": "e2-3", "source": "2", "target": "3", "data": {"label": "Fin"}}
    )
    v["workflow_configurations"]["speaking_plan"]["stop"]["num_words"] = 2
    return v


def test_identical_versions():
    d = diff_versions(BASE, copy.deepcopy(BASE))
    assert d["identical"] and d["changes"] == [] and d["bullets"] == []


def test_layout_only():
    v = copy.deepcopy(BASE)
    v["workflow_json"]["nodes"][0]["position"] = {"x": 50, "y": 0}
    d = diff_versions(BASE, v)
    assert (
        d["changes"] == []
        and d["bullets"] == ["Layout only (nodes moved)"]
        and not d["identical"]
    )


def test_nodes_edges_settings():
    d = diff_versions(BASE, _changed())
    by = {(c["scope"], c["kind"], c["title"]): c for c in d["changes"]}
    accueil = by[("node", "changed", "Accueil")]
    fields = {f["field"]: f for f in accueil["fields"]}
    assert (
        fields["allow_interrupt"]["before"] is True
        and fields["allow_interrupt"]["after"] is False
    )
    ops = {(s["op"], s["text"].strip()) for s in fields["prompt"]["text_diff"]}
    assert ("insert", "une phrase.") in ops and ("delete", "1 à 2 phrases.") in ops
    assert ("node", "added", "Fin") in by
    assert ("edge", "added", "Urgences → Fin (Fin)") in by
    cond = by[("edge", "changed", "Accueil → Urgences (Urgence)")]["fields"][0]
    assert cond["field"] == "condition"
    plan = by[("config", "changed", "Speaking plan")]["fields"]
    assert plan == [
        {
            "field": "speaking_plan.stop.num_words",
            "label": "Speaking plan › stop › num words",
            "before": 0,
            "after": 2,
        }
    ]
    assert d["counts"] == {"added": 2, "removed": 0, "changed": 3}
    assert any(b.startswith("“Accueil”: Prompt rewritten") for b in d["bullets"])
    assert "Added end node “Fin”" in d["bullets"]


def test_first_version_lists_its_graph_only():
    d = diff_versions(None, BASE)
    assert {(c["scope"], c["kind"]) for c in d["changes"]} == {
        ("node", "added"),
        ("edge", "added"),
    }


def test_word_diff_roundtrip():
    a, b = "Bonjour, je suis l'accueil.", "Bonjour, je suis le standard du cabinet."
    ops = word_diff(a, b)
    assert "".join(s["text"] for s in ops if s["op"] != "insert") == a
    assert "".join(s["text"] for s in ops if s["op"] != "delete") == b


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,headers,expected",
    [
        ("/api/v1/workflow/2", [], {"channel": "editor"}),
        (
            "/api/v1/workflow/2",
            [(b"x-api-key", b"dgr_abcdefgh123")],
            {"channel": "api", "api_key_prefix": "dgr_abcd"},
        ),
        (
            "/api/v1/mcp/",
            [(b"authorization", b"Bearer dgr_zyxwvuts99")],
            {"channel": "mcp", "api_key_prefix": "dgr_zyxw"},
        ),
    ],
)
async def test_channel_middleware(path, headers, expected):
    seen = {}

    async def app(scope, receive, send):
        seen.update(versions.current_channel())

    await versions.ChannelMiddleware(app)(
        {"type": "http", "path": path, "headers": headers}, None, None
    )
    assert seen == expected
    assert versions.current_channel() == {"channel": "internal"}


@pytest.fixture
def store(monkeypatch):
    data = {}

    async def get_configuration(org, key):
        return SimpleNamespace(value=data[(org, key)]) if (org, key) in data else None

    async def upsert_configuration(org, key, value):
        data[(org, key)] = copy.deepcopy(value)

    monkeypatch.setattr(versions.db_client, "get_configuration", get_configuration)
    monkeypatch.setattr(
        versions.db_client, "upsert_configuration", upsert_configuration
    )
    return data


@pytest.mark.asyncio
async def test_record_edit_keeps_origin_and_first_author(store):
    draft = SimpleNamespace(id=5, workflow_id=2)
    alice, bob = SimpleNamespace(id=1, email="a@x"), SimpleNamespace(id=2, email="b@x")
    await versions.record_edit(draft, alice, organization_id=1)
    await versions.record_edit(draft, bob, organization_id=1, origin="api")
    meta = await versions.get_meta(1, 2, 5)
    assert meta["origin"] == "internal" and meta["created_by"]["email"] == "a@x"
    assert [e["by"]["email"] for e in meta["edits"]] == ["a@x", "b@x"]
    await versions.record_edit(draft, bob, organization_id=1, only_if_new=True)
    assert len((await versions.get_meta(1, 2, 5))["edits"]) == 2


@pytest.mark.asyncio
async def test_restore_refuses_to_drop_a_draft(store, monkeypatch):
    source = SimpleNamespace(id=2, workflow_id=2, version_number=1)
    draft = SimpleNamespace(id=5, workflow_id=2, version_number=2)
    monkeypatch.setattr(
        versions.brand_db, "get_workflow_version", AsyncMock(return_value=source)
    )
    monkeypatch.setattr(
        versions.db_client, "get_draft_version", AsyncMock(return_value=draft)
    )
    discard = AsyncMock()
    revert = AsyncMock(
        return_value=SimpleNamespace(
            id=6, workflow_id=2, version_number=3, status="draft"
        )
    )
    monkeypatch.setattr(versions.db_client, "discard_workflow_draft", discard)
    monkeypatch.setattr(versions.brand_db, "delete_configuration", AsyncMock())
    monkeypatch.setattr(versions.db_client, "revert_to_version", revert)
    user = SimpleNamespace(id=1, email="a@x")

    with pytest.raises(versions.DraftExists):
        await versions.restore(2, 2, user, organization_id=1)
    discard.assert_not_called()

    restored = await versions.restore(2, 2, user, organization_id=1, replace_draft=True)
    discard.assert_awaited_once_with(2)
    revert.assert_awaited_once_with(2, 2)
    meta = await versions.get_meta(1, 2, restored.id)
    assert meta["origin"] == "restore" and meta["restored_from"] == 1
    assert meta["note"] == "Restored from v1"


def test_settings_left_at_default_show_the_default():
    old = SimpleNamespace(
        workflow_json={}, workflow_configurations={}, template_context_variables={}
    )
    new = SimpleNamespace(
        workflow_json={},
        workflow_configurations={"max_user_idle_timeout": 8},
        template_context_variables={},
    )
    d = diff_versions(versions._snapshot(old), versions._snapshot(new))
    assert d["bullets"] == ["Settings › Idle timeout: 10.0 → 8.0"]
    assert d["counts"] == {"added": 0, "removed": 0, "changed": 1}


def test_first_speaking_plan_compares_with_the_turn_settings():
    old = SimpleNamespace(
        workflow_json={},
        workflow_configurations={"turn_start_strategy": "default"},
        template_context_variables={},
    )
    plan = {
        "start": {
            "wait_seconds": 0.4,
            "smart_endpointing": "off",
            "on_punctuation_seconds": 0.1,
            "on_no_punctuation_seconds": 1.5,
            "on_number_seconds": 0.5,
        },
        "stop": {"num_words": 2, "voice_seconds": 0.2, "backoff_seconds": 1.5},
    }
    new = SimpleNamespace(
        workflow_json={},
        workflow_configurations={
            "speaking_plan": plan,
            "transcript_configuration": {"include_end_timestamps": False},
        },
        template_context_variables={},
    )
    d = diff_versions(versions._snapshot(old), versions._snapshot(new))
    assert d["bullets"] == [
        "Settings › Speaking plan: stop › backoff seconds: 1.0 → 1.5; stop › num words: 0 → 2"
    ]
