from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document

from agents.base import BaseAgent
from agents.intent_extraction_agent import IntentExtractionAgent
from models.user_query import ExtractedIntent, NLDiagnosisResult, UserQueryRequest
from pipeline.nl_diagnosis_pipeline import NLDiagnosisPipeline

_INTENT_DICT = {
    "equipment_id": "machine_3",
    "symptom_description": "Vibration intensity higher than usual on equipment 3",
    "sensor_types": ["vibration", "rotational_speed", "torque"],
    "urgency": "medium",
    "failure_type_hints": ["TWF", "OSF"],
}

_DIAGNOSIS_DICT = {
    "diagnosis": "3번 설비에서 진동 증가가 감지되었습니다. SOP에 따르면 베어링 마모 또는 불균형이 원인일 수 있습니다. 즉시 설비를 점검하고 회전 속도 및 토크 값을 확인하십시오."
}


def _make_mock_vectorstore() -> MagicMock:
    vs = MagicMock()
    vs.similarity_search_with_relevance_scores.return_value = [
        (Document(
            page_content="Check rotational speed and torque. Bearing wear causes vibration.",
            metadata={"document_name": "SOP-OSF-001.md", "chunk_index": 1, "page_number": 0},
        ), 0.88)
    ]
    return vs


def _make_mock_collection() -> MagicMock:
    col = MagicMock()
    col.count.return_value = 2
    return col


async def test_nl_diagnosis_full_run(correlation_id):
    responses = iter([_INTENT_DICT, _DIAGNOSIS_DICT])
    mock_vs = _make_mock_vectorstore()
    mock_col = _make_mock_collection()

    with patch.object(BaseAgent, "_invoke_chain", new_callable=AsyncMock, side_effect=lambda *a, **kw: next(responses)), \
         patch("pipeline.nl_diagnosis_pipeline.get_sop_collection", return_value=mock_col), \
         patch("pipeline.nl_diagnosis_pipeline.get_langchain_vectorstore", return_value=mock_vs):
        result = await NLDiagnosisPipeline().run(
            UserQueryRequest(query="3번 설비에서 진동이 평소보다 심한 것 같아요"),
            correlation_id,
        )

    assert isinstance(result, NLDiagnosisResult)
    assert result.correlation_id == correlation_id
    assert result.intent is not None
    assert result.intent.equipment_id == "machine_3"
    assert result.intent.urgency == "medium"
    assert len(result.related_sop_chunks) == 1
    assert result.diagnosis != ""
    assert "진단" in result.diagnosis or "설비" in result.diagnosis


async def test_nl_diagnosis_with_equipment_id_override(correlation_id):
    """equipment_id를 요청에 직접 지정하면 intent 추출 결과를 덮어써야 한다."""
    responses = iter([_INTENT_DICT, _DIAGNOSIS_DICT])
    mock_vs = _make_mock_vectorstore()
    mock_col = _make_mock_collection()

    with patch.object(BaseAgent, "_invoke_chain", new_callable=AsyncMock, side_effect=lambda *a, **kw: next(responses)), \
         patch("pipeline.nl_diagnosis_pipeline.get_sop_collection", return_value=mock_col), \
         patch("pipeline.nl_diagnosis_pipeline.get_langchain_vectorstore", return_value=mock_vs):
        result = await NLDiagnosisPipeline().run(
            UserQueryRequest(query="설비에서 이상 소음이 납니다", equipment_id="machine_5"),
            correlation_id,
        )

    assert result.intent.equipment_id == "machine_5"


async def test_nl_diagnosis_empty_sop_collection(correlation_id):
    """SOP 컬렉션이 비어 있으면 chunks 없이도 파이프라인이 완료되어야 한다."""
    responses = iter([_INTENT_DICT, _DIAGNOSIS_DICT])
    empty_col = MagicMock()
    empty_col.count.return_value = 0

    with patch.object(BaseAgent, "_invoke_chain", new_callable=AsyncMock, side_effect=lambda *a, **kw: next(responses)), \
         patch("pipeline.nl_diagnosis_pipeline.get_sop_collection", return_value=empty_col), \
         patch("pipeline.nl_diagnosis_pipeline.get_langchain_vectorstore", return_value=MagicMock()):
        result = await NLDiagnosisPipeline().run(
            UserQueryRequest(query="설비 온도가 이상합니다"),
            correlation_id,
        )

    assert result.related_sop_chunks == []
    assert result.diagnosis != ""
