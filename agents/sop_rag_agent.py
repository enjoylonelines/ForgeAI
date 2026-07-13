from __future__ import annotations

from agents.base import BaseAgent, MaxRetriesExceededError, ParseOutputError
from core.config import get_settings
from core.langfuse_client import get_current_trace
from core.logging import get_logger
from models.anomaly_report import AnomalyReport
from models.sop_context import SOPChunk, SOPContext
from prompts import sop_rag_v1 as prompt
from rag.chroma_client import get_langchain_vectorstore, get_sop_collection

logger = get_logger(__name__)


class SOPRAGAgent(BaseAgent):
    def __init__(self, model: str | None = None) -> None:
        super().__init__(
            system_prompt=prompt.SYSTEM,
            model=model,
            prompt_name=prompt.NAME,
            prompt_version=prompt.VERSION,
        )

    async def run(
        self,
        anomaly_report: AnomalyReport,
        failure_type: str | None = None,
        correlation_id: str | None = None,
    ) -> SOPContext:
        self._log("sop_rag_agent_start", correlation_id, equipment_id=anomaly_report.equipment_id)

        collection = get_sop_collection()
        if collection.count() == 0:
            logger.warning({"event": "sop_collection_empty", "correlation_id": correlation_id})
            return SOPContext(
                equipment_id=anomaly_report.equipment_id,
                query_used="",
                chunks=[],
                correlation_id=correlation_id,
            )

        user_msg = prompt.format_user_message(
            anomaly_report.model_dump(mode="json", exclude={"tags", "correlation_id"})
        )
        try:
            data = await self._invoke_chain(user_msg, correlation_id)
            query = data["query"]
        except MaxRetriesExceededError:
            raise
        except Exception as exc:
            raise ParseOutputError(f"SOPRAGAgent parse failed: {exc}") from exc

        self._log("sop_rag_query", correlation_id, query=query)

        settings = get_settings()
        n_results = min(settings.top_k_retrieval, collection.count())
        vectorstore = get_langchain_vectorstore()

        filter_dict = (
            {"failure_type": {"$in": [failure_type]}}
            if failure_type and failure_type != "NONE"
            else None
        )

        lf_trace = get_current_trace()
        _lf_span = lf_trace.span(
            name="vector_search",
            input={"query": query, "k": n_results, "filter": filter_dict},
            metadata={"correlation_id": correlation_id},
        ) if lf_trace else None

        docs_with_scores = vectorstore.similarity_search_with_relevance_scores(
            query, k=n_results, filter=filter_dict
        )

        # failure_type 필터 결과가 부족하면 필터 없이 재검색
        if filter_dict and len(docs_with_scores) < n_results:
            self._log("sop_rag_fallback", correlation_id, reason="filtered_results_insufficient")
            docs_with_scores = vectorstore.similarity_search_with_relevance_scores(
                query, k=n_results
            )

        if _lf_span:
            _lf_span.end(output={"result_count": len(docs_with_scores)})

        chunks: list[SOPChunk] = []
        for doc, score in docs_with_scores:
            meta = doc.metadata
            chunk_id = f"{meta['document_name']}::chunk::{meta['chunk_index']}"
            chunks.append(SOPChunk(
                chunk_id=chunk_id,
                document_name=meta["document_name"],
                page_number=meta.get("page_number"),
                text=doc.page_content,
                relevance_score=round(score, 4),
            ))

        self._log("sop_rag_agent_complete", correlation_id, chunk_count=len(chunks))
        return SOPContext(
            equipment_id=anomaly_report.equipment_id,
            query_used=query,
            chunks=chunks,
            correlation_id=correlation_id,
        )
