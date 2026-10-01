"""Local knowledge-base document processing (replaces the Dograh MPS call).

Upstream sends every uploaded file to Dograh's Model Proxy Service, which
converts it (docling) and chunks it; only the embedding runs locally. OxeePhone
never reaches Dograh, so this module does the conversion and chunking in
process and returns the same shape as MPS ``/api/v1/document/process``:

    {"mode", "docling_metadata", "full_text",
     "chunks": [{"chunk_text", "contextualized_text", "chunk_index",
                 "chunk_metadata", "token_count"}]}

Parsing is deliberately light (pypdf, python-docx): text PDFs, DOCX, TXT, MD
and JSON. No OCR, so scanned PDFs are rejected with a clear message.
"""

import json
import math
import os
import re
from dataclasses import dataclass, field

# ~4 characters per token is the usual estimate for BPE tokenizers; good enough
# to size chunks without shipping a tokenizer.
CHARS_PER_TOKEN = 4
SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt", ".md", ".json")

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?;:])\s+")
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


class DocumentProcessingError(ValueError):
    """User-facing error: stored as the document's error message."""


@dataclass
class Block:
    text: str
    headings: list[str] = field(default_factory=list)
    page: int | None = None


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


# --------------------------------------------------------------------- parsing


def _read_text_file(path: str) -> str:
    with open(path, "rb") as f:
        raw = f.read()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _blocks_from_text(text: str, *, markdown: bool) -> list[Block]:
    blocks: list[Block] = []
    headings: list[str] = []
    paragraph: list[str] = []

    def flush():
        body = "\n".join(paragraph).strip()
        if body:
            blocks.append(Block(body, list(headings)))
        paragraph.clear()

    for line in text.splitlines():
        match = _MARKDOWN_HEADING.match(line.strip()) if markdown else None
        if match:
            flush()
            level = len(match.group(1))
            headings[:] = headings[: level - 1] + [match.group(2).strip()]
        elif not line.strip():
            flush()
        else:
            paragraph.append(line.rstrip())
    flush()
    return blocks


def _blocks_from_pdf(path: str) -> list[Block]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(path)
    except Exception as e:  # pypdf raises many types for corrupt files
        raise DocumentProcessingError(f"Could not read this PDF: {e}") from e
    if reader.is_encrypted:
        raise DocumentProcessingError(
            "This PDF is password-protected. Upload an unprotected copy."
        )

    blocks: list[Block] = []
    for number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for paragraph in re.split(r"\n\s*\n", text):
            paragraph = " ".join(paragraph.split())
            if paragraph:
                blocks.append(Block(paragraph, page=number))
    if not blocks:
        raise DocumentProcessingError(
            "No text found in this PDF. It is probably a scanned document; "
            "OCR is not supported yet, upload a PDF with a text layer."
        )
    return blocks


def _blocks_from_docx(path: str) -> list[Block]:
    import docx

    try:
        document = docx.Document(path)
    except Exception as e:
        raise DocumentProcessingError(f"Could not read this Word file: {e}") from e

    blocks: list[Block] = []
    headings: list[str] = []
    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = docx.text.paragraph.Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue
            style = (paragraph.style.name or "") if paragraph.style else ""
            if style.lower().startswith("heading") or style.lower() == "title":
                digits = "".join(ch for ch in style if ch.isdigit())
                level = int(digits) if digits else 1
                headings[:] = headings[: level - 1] + [text]
            else:
                blocks.append(Block(text, list(headings)))
        elif tag == "tbl":
            table = docx.table.Table(child, document)
            rows = [
                " | ".join(cell.text.strip() for cell in row.cells)
                for row in table.rows
            ]
            text = "\n".join(row for row in rows if row.strip(" |"))
            if text:
                blocks.append(Block(text, list(headings)))
    return blocks


def parse_document(path: str, filename: str) -> tuple[list[Block], dict]:
    extension = os.path.splitext(filename)[1].lower()
    if extension == ".pdf":
        blocks = _blocks_from_pdf(path)
    elif extension == ".docx":
        blocks = _blocks_from_docx(path)
    elif extension == ".md":
        blocks = _blocks_from_text(_read_text_file(path), markdown=True)
    elif extension == ".txt":
        blocks = _blocks_from_text(_read_text_file(path), markdown=False)
    elif extension == ".json":
        try:
            data = json.loads(_read_text_file(path))
        except json.JSONDecodeError as e:
            raise DocumentProcessingError(f"Invalid JSON file: {e}") from e
        pretty = json.dumps(data, indent=2, ensure_ascii=False)
        blocks = [Block(part) for part in pretty.split("\n\n") if part.strip()]
    elif extension == ".doc":
        raise DocumentProcessingError(
            "Legacy .doc files are not supported. Save the file as .docx and "
            "upload it again."
        )
    else:
        raise DocumentProcessingError(
            f"Unsupported file type '{extension or filename}'. Supported: "
            + ", ".join(SUPPORTED_EXTENSIONS)
        )

    if not blocks:
        raise DocumentProcessingError("The document contains no text.")
    metadata = {
        "processor": "oxeephone-local",
        "source_format": extension.lstrip("."),
        "num_blocks": len(blocks),
    }
    pages = {block.page for block in blocks if block.page}
    if pages:
        metadata["num_pages"] = max(pages)
    return blocks, metadata


# -------------------------------------------------------------------- chunking


def _split_oversized(text: str, max_chars: int) -> list[str]:
    """Split text longer than max_chars on sentences, then on words."""
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_BOUNDARY.split(text):
        units = [sentence] if len(sentence) <= max_chars else sentence.split()
        for unit in units:
            candidate = f"{current} {unit}".strip() if current else unit
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    pieces.append(current)
                current = unit[:max_chars]
    if current:
        pieces.append(current)
    return pieces


def chunk_blocks(blocks: list[Block], max_tokens: int) -> list[dict]:
    """Greedy packing of consecutive blocks sharing the same heading path."""
    max_chars = max(1, max_tokens) * CHARS_PER_TOKEN
    chunks: list[dict] = []
    buffer: list[str] = []
    buffer_headings: list[str] = []
    buffer_pages: set[int] = set()

    def flush():
        if not buffer:
            return
        text = "\n".join(buffer)
        context = " > ".join(buffer_headings)
        chunks.append(
            {
                "chunk_text": text,
                "contextualized_text": f"{context}\n{text}" if context else text,
                "chunk_index": len(chunks),
                "chunk_metadata": {
                    "headings": list(buffer_headings),
                    "pages": sorted(buffer_pages),
                },
                "token_count": estimate_tokens(text),
            }
        )
        buffer.clear()
        buffer_pages.clear()

    for block in blocks:
        for piece in _split_oversized(block.text, max_chars):
            same_section = block.headings == buffer_headings
            fits = len("\n".join([*buffer, piece])) <= max_chars
            if buffer and not (same_section and fits):
                flush()
            if not buffer:
                buffer_headings[:] = block.headings
            buffer.append(piece)
            if block.page:
                buffer_pages.add(block.page)
    flush()
    return chunks


def process_document_locally(
    *,
    file_path: str,
    filename: str,
    retrieval_mode: str,
    max_tokens: int,
) -> dict:
    """Synchronous (CPU-bound): call through ``asyncio.to_thread``."""
    blocks, metadata = parse_document(file_path, filename)
    full_text = "\n\n".join(block.text for block in blocks)
    if retrieval_mode == "full_document":
        return {
            "mode": retrieval_mode,
            "docling_metadata": metadata,
            "full_text": full_text,
            "chunks": [],
        }
    chunks = chunk_blocks(blocks, max_tokens)
    metadata["num_chunks"] = len(chunks)
    return {
        "mode": retrieval_mode,
        "docling_metadata": metadata,
        "full_text": full_text,
        "chunks": chunks,
    }
