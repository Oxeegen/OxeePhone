"""OxeePhone: preview of the Files page documents."""

from types import SimpleNamespace

import pytest

from api.brand import files


def _doc(filename, full_text=None, key="knowledge_base/1/u/x"):
    return SimpleNamespace(filename=filename, full_text=full_text, custom_metadata={"s3_key": key})


@pytest.fixture
def store(monkeypatch):
    from api.db import db_client

    state = {"doc": None, "bytes": b""}

    async def get_document_by_uuid(document_uuid, organization_id):
        return state["doc"] if organization_id == 1 else None

    async def stored(key):
        return state["bytes"]

    monkeypatch.setattr(db_client, "get_document_by_uuid", get_document_by_uuid)
    monkeypatch.setattr(files, "_stored_file", stored)
    return state


@pytest.mark.asyncio
async def test_markdown_is_read_from_the_file(store):
    store["doc"] = _doc("Procédures.MD")
    store["bytes"] = "# Horaires\n\n- lundi : 9h–18h\n".encode()
    out = await files.preview(1, "u")
    assert out["format"] == "markdown" and out["source"] == "file"
    assert out["content"].startswith("# Horaires") and not out["truncated"]
    with pytest.raises(LookupError):
        await files.preview(2, "u")  # other organization


@pytest.mark.asyncio
async def test_other_documents_show_their_extracted_text(store):
    store["doc"] = _doc("tarifs.pdf", full_text="## Tarifs\n\n| Acte | Prix |")
    out = await files.preview(1, "u")
    assert out["source"] == "extracted" and out["format"] == "markdown"
    store["doc"] = _doc("scan.pdf")
    with pytest.raises(files.PreviewUnavailable):
        await files.preview(1, "u")
