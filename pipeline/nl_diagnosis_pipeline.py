from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from agents.base import BaseAgent, ParseOutputError
from agents.intent_extraction_agent import IntentExtractionAgent
from core.config import get_settings
from core.langfuse_client import get_langfuse
from core.logging import get_logger
from models.sop_context import SOPChunk
from models.user_query import ExtractedIntent, NLDiagnosisResult, UserQueryRequest
from prompts import nl_diagnosis_v1 as diag_prompt
from rag.chroma_client import get_langchain_vectorstore, get_sop_collection

logger = get_logger(__name__)


class _NLGraphState(BaseModel):
    query: str
    correlation_id: str
    equipment_id_override: str | None = None

    intent: ExtractedIntent | None = None
    sop_chunks: list[SOPChunk] = []
    diagnosis: str = ""


class NLDiagnosisPipeline:
    def __init__(self, model: str | None = None) -> None:
        self._intent_agent = IntentExtractionAgent(model=model)
        self._diagnosis_agent = BaseAgent(
            system_prompt=diag_prompt.SYSTEM,
            model=model,
            prompt_name=diag_prompt.NAME,
            prompt_version=diag_prompt.VERSION,
        )
        self._graph = self._build_graph()

    # ── nodes ──────────────────────────────────────────────────────────────────

    async def _node_intent_extraction(self, state: _NLGraphState) -> dict[str, Any]:
        intent = await self._intent_agent.run(
            state.query,
            equipment_id_override=state.equipment_id_override,
            correlation_id=state.correlation_id,
        )
        return {"intent": intent}

    async def _node_rag_search(self, state: _NLGraphState) -> dict[str, Any]:
        assert state.intent is not None
        collection = get_sop_collection()
        if collection.count() == 0:
            logger.warning({"event": "nl_sop_collection_empty", "correlation_id": state.correlation_id})
            return {"sop_chunks": []}

        settings = get_settings()
        vectorstore = get_langchain_vectorstore()
        n_results = min(settings.top_k_retrieval, collection.count())

        search_query = state.intent.symptom_description
        if state.intent.sensor_types:
            search_query = f"{search_query} {' '.join(state.intent.sensor_types)}"

        failure_hints = state.intent.failure_type_hints
        filter_dict = {"failure_type": {"$in": failure_hints}} if failure_hints else None

        docs_with_scores = vectorstore.similarity_search_with_relevance_scores(
            search_query, k=n_results, filter=filter_dict
        )
        if filter_dict and len(docs_with_scores) < n_results:
            docs_with_scores = vectorstore.similarity_search_with_relevance_scores(
                search_query, k=n_results
            )

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

        logger.info({
            "event": "nl_rag_search_complete",
            "correlation_id": state.correlation_id,
            "chunk_count": len(chunks),
        })
        return {"sop_chunks": chunks}

    async def _node_diagnosis_response(self, state: _NLGraphState) -> dict[str, Any]:
        assert state.intent is not None
        user_msg = diag_prompt.format_user_message(
            query=state.query,
            intent=state.intent.model_dump(),
            sop_chunks=[c.model_dump() for c in state.sop_chunks],
        )
        try:
            data: dict = await self._diagnosis_agent._invoke_chain(user_msg, state.correlation_id)
            diagnosis = data.get("diagnosis", "진단 응답을 생성하지 못했습니다.")
        except Exception as exc:
            raise ParseOutputError(f"NLDiagnosisPipeline diagnosis failed: {exc}") from exc

        return {"diagnosis": diagnosis}

    # ── graph builder ──────────────────────────────────────────────────────────

    def _build_graph(self) -> Any:
        builder = StateGraph(_NLGraphState)
        builder.add_node("intent_extraction", self._node_intent_extraction)
        builder.add_node("rag_search", self._node_rag_search)
        builder.add_node("diagnosis_response", self._node_diagnosis_response)

        builder.add_edge(START, "intent_extraction")
        builder.add_edge("intent_extraction", "rag_search")
        builder.add_edge("rag_search", "diagnosis_response")
        builder.add_edge("diagnosis_response", END)

        return builder.compile()

    # ── public entry point ─────────────────────────────────────────────────────

    async def run(self, request: UserQueryRequest, correlation_id: str) -> NLDiagnosisResult:
        logger.info({
            "event": "nl_diagnosis_start",
            "correlation_id": correlation_id,
            "query": request.query[:80],
        })

        lf = get_langfuse()

        async def _run_graph() -> tuple:
            initial = _NLGraphState(
                query=request.query,
                correlation_id=correlation_id,
                equipment_id_override=request.equipment_id,
            )
            raw: dict = await self._graph.ainvoke(initial)
            final = _NLGraphState.model_validate(raw)

            logger.info({
                "event": "nl_diagnosis_complete",
                "correlation_id": correlation_id,
                "urgency": final.intent.urgency if final.intent else None,
                "chunk_count": len(final.sop_chunks),
            })

            return NLDiagnosisResult(
                query=request.query,
                intent=final.intent,
                diagnosis=final.diagnosis,
                related_sop_chunks=final.sop_chunks,
                correlation_id=correlation_id,
            ), final

        if lf:
            with lf.start_as_current_observation(
                name="nl_diagnosis_pipeline",
                as_type="agent",
                input={"query": request.query, "equipment_id": request.equipment_id},
                metadata={"correlation_id": correlation_id},
            ) as _lf_root:
                nl_result, final = await _run_graph()
                _lf_root.update(output={
                    "urgency": final.intent.urgency if final.intent else None,
                    "diagnosis_length": len(final.diagnosis),
                })
            lf.flush()
        else:
            nl_result, _ = await _run_graph()

        return nl_result
