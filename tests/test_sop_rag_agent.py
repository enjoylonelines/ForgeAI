from __future__ import annotations

import pytest

from agents.sop_rag_agent import SOPRAGAgent
from models.sop_context import SOPContext


async def test_sop_rag_agent_success(mock_ollama_chat, mock_ollama_embed, mock_chroma_collection, sample_anomaly_report, correlation_id):
    mock_ollama_chat.return_value = {"query": "tool wear failure CNC replacement procedure corrective action"}
    agent = SOPRAGAgent()
    context = await agent.run(sample_anomaly_report, correlation_id)

    assert isinstance(context, SOPContext)
    assert context.query_used != ""
    assert len(context.chunks) > 0
    assert context.correlation_id == correlation_id
    assert 0.0 <= context.chunks[0].relevance_score <= 1.0


async def test_sop_rag_agent_empty_collection(mock_ollama_chat, mock_ollama_embed, sample_anomaly_report, correlation_id):
    from unittest.mock import MagicMock, patch
    empty_col = MagicMock()
    empty_col.count.return_value = 0

    with patch("agents.sop_rag_agent.get_sop_collection", return_value=empty_col):
        agent = SOPRAGAgent()
        context = await agent.run(sample_anomaly_report, correlation_id)

    assert context.chunks == []
    assert context.query_used == ""
    mock_ollama_chat.assert_not_called()


async def test_sop_rag_agent_relevance_score_range(mock_ollama_chat, mock_ollama_embed, mock_chroma_collection, sample_anomaly_report, correlation_id):
    mock_ollama_chat.return_value = {"query": "test query"}
    agent = SOPRAGAgent()
    context = await agent.run(sample_anomaly_report, correlation_id)

    for chunk in context.chunks:
        assert 0.0 <= chunk.relevance_score <= 1.0, f"Score {chunk.relevance_score} out of range"


async def test_sop_rag_agent_uses_failure_type_filter(mock_ollama_chat, mock_ollama_embed, mock_chroma_collection, mock_vectorstore, sample_anomaly_report, correlation_id):
    # sample_anomaly_report.tags = {"machine_type": "M", "failure_types": "TWF"}
    mock_ollama_chat.return_value = {"query": "tool wear failure procedure"}
    agent = SOPRAGAgent()
    await agent.run(sample_anomaly_report, correlation_id)

    first_call_kwargs = mock_vectorstore.similarity_search_with_relevance_scores.call_args_list[0].kwargs
    assert first_call_kwargs.get("filter") == {"failure_type": {"$in": ["TWF"]}}


async def test_sop_rag_agent_no_filter_without_tags(mock_ollama_chat, mock_ollama_embed, mock_chroma_collection, mock_vectorstore, correlation_id):
    from datetime import datetime, timezone
    from models.anomaly_report import AnomalyReport

    report_no_tags = AnomalyReport(
        equipment_id="M-00001",
        timestamp=datetime(2026, 6, 3, tzinfo=timezone.utc),
        has_anomaly=True,
        anomalies=[],
        summary="anomaly detected",
        raw_log_snippet="{}",
        tags={},
    )
    mock_ollama_chat.return_value = {"query": "equipment failure procedure"}
    agent = SOPRAGAgent()
    await agent.run(report_no_tags, correlation_id)

    call_kwargs = mock_vectorstore.similarity_search_with_relevance_scores.call_args.kwargs
    assert call_kwargs.get("filter") is None
