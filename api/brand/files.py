"""Preview of the documents of the Files page (knowledge base).

Text documents (Markdown, plain text) are read back from storage as they were
uploaded; other documents kept whole (retrieval mode "full document") show
their extracted text, which document conversion writes as Markdown.
"""

from __future__ import annotations

import os
import tempfile

from api.db import db_client

TEXT_FORMATS = {".md": "markdown", ".markdown": "markdown", ".txt": "text"}
MAX_PREVIEW_BYTES = 2 * 1024 * 1024


class PreviewUnavailable(Exception):
    pass


def text_format(filename: str) -> str | None:
    return TEXT_FORMATS.get(os.path.splitext(filename or "")[1].lower())


async def _stored_file(key: str) -> bytes | None:
    from api.services.storage import storage_fs

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "document")
        if not await storage_fs.adownload_file(key, path):
            return None
        with open(path, "rb") as f:
            return f.read(MAX_PREVIEW_BYTES + 1)


async def preview(organization_id: int, document_uuid: str) -> dict:
    document = await db_client.get_document_by_uuid(
        document_uuid=document_uuid, organization_id=organization_id
    )
    if document is None:
        raise LookupError("document not found")
    fmt = text_format(document.filename)
    key = (document.custom_metadata or {}).get("s3_key")
    if fmt and key:
        data = await _stored_file(key)
        if data is not None:
            return {
                "filename": document.filename,
                "format": fmt,
                "source": "file",
                "content": data[:MAX_PREVIEW_BYTES].decode("utf-8", errors="replace"),
                "truncated": len(data) > MAX_PREVIEW_BYTES,
            }
    if document.full_text:
        text = document.full_text
        return {
            "filename": document.filename,
            "format": "markdown",
            "source": "extracted",
            "content": text[:MAX_PREVIEW_BYTES],
            "truncated": len(text) > MAX_PREVIEW_BYTES,
        }
    raise PreviewUnavailable(
        "No preview for this document: only text files (.md, .txt) and documents "
        "kept whole can be shown."
    )
