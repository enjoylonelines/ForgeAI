from __future__ import annotations

from pydantic import BaseModel


class SOPChunk(BaseModel):
    chunk_id: str
    document_name: str
    page_number: int | None = None
    text: str
    relevance_score: float


class SOPContext(BaseModel):
    equipment_id: str
    query_used: str
    chunks: list[SOPChunk] = []
    correlation_id: str | None = None
