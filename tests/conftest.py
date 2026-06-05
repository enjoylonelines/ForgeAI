from __future__ import annotations

import math
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document

from agents.base import BaseAgent
from models.action_plan import ActionPlan, ActionStep
from models.anomaly_report import AnomalyDetail, AnomalyReport
from models.equipment_log import EquipmentLog, SensorReading
from models.sop_context import SOPChunk, SOPContext
from models.validation_result import ValidationResult

_CID = "test-correlation-id-001"
_NOW = datetime(2026, 6, 3, 8, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def correlation_id() -> str:
    return _CID


@pytest.fixture
def sample_equipment_log() -> EquipmentLog:
    return EquipmentLog(
        equipment_id="M-12345",
        timestamp=_NOW,
        log_level="ERROR",
        readings=[
            SensorReading(sensor_id="air_temperature_k", unit="K", value=298.1),
            SensorReading(sensor_id="process_temperature_k", unit="K", value=308.6),
            SensorReading(sensor_id="rotational_speed_rpm", unit="rpm", value=1251.0),
            SensorReading(sensor_id="torque_nm", unit="Nm", value=42.8),
            SensorReading(sensor_id="tool_wear_min", unit="min", value=216.0),
        ],
        message="Machine failure detected: TWF",
        tags={"machine_type": "M", "failure_types": "TWF"},
    )


@pytest.fixture
def sample_anomaly_report() -> AnomalyReport:
    return AnomalyReport(
        equipment_id="M-12345",
        timestamp=_NOW,
        has_anomaly=True,
        anomalies=[
            AnomalyDetail(
                sensor_id="tool_wear_min",
                observed_value=216.0,
                expected_range=(0.0, 200.0),
                severity="HIGH",
                description="Tool wear exceeds 200 min threshold — TWF risk",
            )
        ],
        summary="Tool wear failure risk detected on equipment M-12345",
        raw_log_snippet='{"tool_wear_min": 216.0}',
        tags={"machine_type": "M", "failure_types": "TWF"},
        correlation_id=_CID,
    )


@pytest.fixture
def sample_sop_context() -> SOPContext:
    return SOPContext(
        equipment_id="M-12345",
        query_used="tool wear failure CNC machining replacement procedure",
        chunks=[
            SOPChunk(
                chunk_id="SOP-MNT-001-tool-wear-failure.md::chunk::2",
                document_name="SOP-MNT-001-tool-wear-failure.md",
                page_number=0,
                text="공구 교체 후 스핀들 토크 확인 및 시운전 가공 실시. 마모량이 규격치(VB = 0.3mm)를 초과하면 즉시 폐기한다.",
                relevance_score=0.91,
            ),
            SOPChunk(
                chunk_id="SOP-MNT-001-tool-wear-failure.md::chunk::3",
                document_name="SOP-MNT-001-tool-wear-failure.md",
                page_number=0,
                text="공구 육안 검사: 스핀들에서 공구를 탈착하여 마모, 파손, 치핑 여부를 확인한다.",
                relevance_score=0.87,
            ),
        ],
        correlation_id=_CID,
    )


@pytest.fixture
def sample_action_plan() -> ActionPlan:
    return ActionPlan(
        equipment_id="M-12345",
        generated_at=_NOW,
        steps=[
            ActionStep(
                step_number=1,
                action="Stop the CNC machine after current cycle completes",
                responsible_role="maintenance_technician",
                priority="P1",
                estimated_duration_minutes=5,
                sop_reference="SOP-MNT-001-tool-wear-failure.md::chunk::2",
            ),
            ActionStep(
                step_number=2,
                action="Remove and inspect tool for wear and chipping",
                responsible_role="maintenance_technician",
                priority="P1",
                estimated_duration_minutes=15,
                sop_reference="SOP-MNT-001-tool-wear-failure.md::chunk::3",
            ),
        ],
        escalation_required=False,
        correlation_id=_CID,
    )


def _make_unit_vec(dim: int, hot_index: int) -> list[float]:
    vec = [0.0] * dim
    vec[hot_index % dim] = 1.0
    return vec


@pytest.fixture
def mock_ollama_chat():
    """Patches BaseAgent._invoke_chain to return dicts without hitting Ollama."""
    with patch.object(BaseAgent, "_invoke_chain", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def mock_ollama_embed():
    """Patches OllamaEmbeddings used in agents and embedder."""
    vec = _make_unit_vec(768, 0)
    mock_emb = MagicMock()
    mock_emb.aembed_query = AsyncMock(return_value=vec)
    mock_emb.aembed_documents = AsyncMock(return_value=[vec])
    with patch("agents.hallucination_validator.get_embeddings", return_value=mock_emb), \
         patch("rag.embedder.get_embeddings", return_value=mock_emb):
        yield mock_emb


@pytest.fixture
def mock_vectorstore():
    """Standalone LangChain Chroma vectorstore mock."""
    vs = MagicMock()
    vs.similarity_search_with_relevance_scores.return_value = [
        (Document(
            page_content="SOP text chunk about tool wear replacement procedure",
            metadata={"document_name": "SOP-MNT-001.md", "chunk_index": 2, "page_number": 0},
        ), 0.91)
    ]
    return vs


@pytest.fixture
def mock_chroma_collection(mock_vectorstore):
    """Raw ChromaDB collection mock + LangChain vectorstore mock patched into agents."""
    col = MagicMock()
    col.count.return_value = 2
    col.get.return_value = {
        "ids": ["SOP-MNT-001.md::chunk::2"],
        "embeddings": [_make_unit_vec(768, 0)],
    }
    with patch("agents.sop_rag_agent.get_sop_collection", return_value=col), \
         patch("agents.sop_rag_agent.get_langchain_vectorstore", return_value=mock_vectorstore), \
         patch("agents.hallucination_validator.get_sop_collection", return_value=col), \
         patch("rag.chroma_client.get_sop_collection", return_value=col):
        yield col
