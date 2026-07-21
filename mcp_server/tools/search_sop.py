"""search_sop MCP tool — v1.0.0"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

# 출력 토큰 예산: 청크당 최대 chars, 전체 최대 chars
_MAX_CHUNK_CHARS = 600
_MAX_TOTAL_CHARS = 2_400

TOOL_VERSION = "1.0.0"

VALID_FAILURE_TYPES = {"TWF", "HDF", "PWF", "OSF", "RNF"}


class SearchSOPInput(BaseModel):
    query: str = Field(..., min_length=3, max_length=500, description="자연어 검색어")
    failure_type: str | None = Field(
        None,
        description="AI4I 고장 유형 필터 — TWF | HDF | PWF | OSF | RNF. 생략 시 전체 검색.",
    )
    top_k: int = Field(3, ge=1, le=5, description="반환할 최대 청크 수 (1–5)")

    @field_validator("failure_type", mode="before")
    @classmethod
    def normalise_failure_type(cls, v: str | None) -> str | None:
        if v is None:
            return None
        upper = v.strip().upper()
        if upper not in VALID_FAILURE_TYPES:
            raise ValueError(
                f"failure_type must be one of {sorted(VALID_FAILURE_TYPES)}, got '{v}'"
            )
        return upper


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"…[{len(text) - limit} chars truncated]"


def run_search_sop(query: str, failure_type: str | None, top_k: int) -> dict:
    """ChromaDB에서 SOP 청크를 검색한다. 임베딩 모델이 필요하므로 lazy import."""
    from rag.chroma_client import get_langchain_vectorstore, get_sop_collection

    collection = get_sop_collection()
    count = collection.count()
    if count == 0:
        return {
            "tool": "search_sop",
            "version": TOOL_VERSION,
            "query": query,
            "failure_type_filter": failure_type,
            "chunks": [],
            "note": "SOP 컬렉션이 비어 있습니다. 문서를 먼저 ingestion하세요.",
        }

    n_results = min(top_k, count)
    vectorstore = get_langchain_vectorstore()

    filter_dict = (
        {"failure_type": {"$in": [failure_type]}} if failure_type else None
    )

    docs_and_scores = vectorstore.similarity_search_with_relevance_scores(
        query, k=n_results, filter=filter_dict
    )

    # 필터 결과가 부족하면 필터 없이 재검색
    if filter_dict and len(docs_and_scores) < n_results:
        docs_and_scores = vectorstore.similarity_search_with_relevance_scores(
            query, k=n_results
        )

    chunks = []
    total_chars = 0
    for doc, score in docs_and_scores:
        if total_chars >= _MAX_TOTAL_CHARS:
            break
        meta = doc.metadata
        remaining = _MAX_TOTAL_CHARS - total_chars
        text = _truncate(doc.page_content, min(_MAX_CHUNK_CHARS, remaining))
        total_chars += len(doc.page_content)
        chunks.append(
            {
                "chunk_id": f"{meta['document_name']}::chunk::{meta.get('chunk_index', '?')}",
                "document_name": meta["document_name"],
                "page_number": meta.get("page_number"),
                "relevance_score": round(score, 4),
                "text": text,
            }
        )

    return {
        "tool": "search_sop",
        "version": TOOL_VERSION,
        "query": query,
        "failure_type_filter": failure_type,
        "chunks": chunks,
    }
