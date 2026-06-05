from __future__ import annotations

import io
import re
from datetime import datetime, timezone

from pydantic import BaseModel

from core.config import get_settings
from core.logging import get_logger
from rag.chroma_client import get_sop_collection
from rag.embedder import embed_texts

logger = get_logger(__name__)

_MIN_CHUNK_CHARS = 50

_FAILURE_TYPE_MAP = {
    "tool-wear": "TWF",
    "heat-dissipation": "HDF",
    "power-failure": "PWF",
    "overstrain": "OSF",
    "random": "RNF",
}


def _extract_failure_type(filename: str) -> str:
    lower = filename.lower()
    for keyword, code in _FAILURE_TYPE_MAP.items():
        if keyword in lower:
            return code
    return ""


class IngestResult(BaseModel):
    document_name: str
    chunk_count: int
    skipped_chunks: int
    collection_total: int


async def ingest_document(
    *,
    file_bytes: bytes,
    filename: str,
    content_type: str,
    equipment_tags: list[str] | None = None,
) -> IngestResult:
    settings = get_settings()

    if content_type == "application/pdf" or filename.lower().endswith(".pdf"):
        pages = _extract_pdf_text(file_bytes)
    else:
        text = file_bytes.decode("utf-8", errors="replace")
        text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
        pages = [(0, text)]

    # Build flat list of (chunk_index, page_num, text)
    indexed: list[tuple[int, int, str]] = []
    idx = 0
    for page_num, page_text in pages:
        for chunk in _chunk_text(page_text, settings.chunk_size, settings.chunk_overlap):
            indexed.append((idx, page_num, chunk))
            idx += 1

    collection = get_sop_collection()
    tags_str = ",".join(equipment_tags or [])
    now = datetime.now(timezone.utc).isoformat()

    all_ids = [f"{filename}::chunk::{i}" for i, _, _ in indexed]
    existing_ids = set(collection.get(ids=all_ids)["ids"])

    to_add = [(chunk_idx, page_num, text) for chunk_idx, page_num, text in indexed
              if f"{filename}::chunk::{chunk_idx}" not in existing_ids]
    skipped = len(indexed) - len(to_add)

    if to_add:
        texts_only = [text for _, _, text in to_add]
        embeddings = await embed_texts(texts_only)

        new_ids = [f"{filename}::chunk::{chunk_idx}" for chunk_idx, _, _ in to_add]
        new_docs = texts_only
        failure_type = _extract_failure_type(filename)
        new_metas = [
            {
                "document_name": filename,
                "page_number": page_num,
                "chunk_index": chunk_idx,
                "ingested_at": now,
                "equipment_tags": tags_str,
                "failure_type": failure_type,
            }
            for chunk_idx, page_num, _ in to_add
        ]
        collection.add(ids=new_ids, embeddings=embeddings, documents=new_docs, metadatas=new_metas)

    total = collection.count()
    logger.info({
        "event": "ingest_complete",
        "document": filename,
        "new_chunks": len(to_add),
        "skipped_chunks": skipped,
        "collection_total": total,
    })
    return IngestResult(
        document_name=filename,
        chunk_count=len(to_add),
        skipped_chunks=skipped,
        collection_total=total,
    )


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= chunk_size:
            current = (current + "\n\n" + para).strip()
        else:
            if current and len(current) >= _MIN_CHUNK_CHARS:
                chunks.append(current)
            if len(para) <= chunk_size:
                current = para
            else:
                sentences = para.replace(". ", ".|").split("|")
                for sent in sentences:
                    if len(current) + len(sent) + 1 <= chunk_size:
                        current = (current + " " + sent).strip()
                    else:
                        if current and len(current) >= _MIN_CHUNK_CHARS:
                            chunks.append(current)
                        current = sent[-chunk_size:] if len(sent) > chunk_size else sent

    if current and len(current) >= _MIN_CHUNK_CHARS:
        chunks.append(current)

    if overlap > 0 and len(chunks) > 1:
        overlapped: list[str] = [chunks[0]]
        for i in range(1, len(chunks)):
            tail = chunks[i - 1][-overlap:]
            overlapped.append((tail + " " + chunks[i]).strip())
        return overlapped

    return chunks


def _extract_pdf_text(file_bytes: bytes) -> list[tuple[int, str]]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(file_bytes))
    pages: list[tuple[int, str]] = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages.append((i + 1, text))
    return pages
