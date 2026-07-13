from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import pytest
from langchain_core.documents import Document

from agents.base import BaseAgent
from agents.diagnostic_agent import DiagnosticAgent
from models.diagnostic_result import DiagnosticResult
from models.equipment_log import EquipmentLog, SensorReading
from pipeline.forge_pipeline import ForgePipeline, PipelineResult

_NOW_ISO = "2026-06-03T08:00:00+00:00"

_RISK_ASSESSMENT_DICT = {
    "equipment_id": "M-12345",
    "assessed_at": _NOW_ISO,
    "risk_level": "WARNING",
    "risk_factors": [
        {
            "sensor_id": "tool_wear_min",
            "current_value": 216.0,
            "safe_max": 250.0,
            "safe_min": 0.0,
            "utilization_pct": 86.4,
            "description": "Tool wear at 86% of safe range — approaching replacement threshold",
        }
    ],
    "summary": "Tool wear is approaching the replacement threshold.",
    "recommended_action": "Schedule tool inspection within this shift.",
}

_PERCEPTION_DICT = {
    "equipment_id": "M-12345",
    "timestamp": _NOW_ISO,
    "has_anomaly": True,
    "anomalies": [{"sensor_id": "tool_wear_min", "observed_value": 216.0,
                   "expected_range": [0, 200], "severity": "HIGH",
                   "description": "TWF risk"}],
    "summary": "Tool wear failure on M-12345",
    "raw_log_snippet": '{"tool_wear_min": 216.0}',
}

_SOP_QUERY_DICT = {"query": "tool wear failure replacement procedure"}

_ACTION_PLAN_DICT = {
    "equipment_id": "M-12345",
    "generated_at": _NOW_ISO,
    "steps": [
        {
            "step_number": 1,
            "action": "Stop machine and inspect tool for wear",
            "responsible_role": "maintenance_technician",
            "priority": "P1",
            "estimated_duration_minutes": 10,
            "sop_reference": "SOP-MNT-001.md::chunk::2",
        }
    ],
    "escalation_required": False,
    "escalation_reason": None,
}


def _make_mock_col(embed_vec: list[float]) -> MagicMock:
    col = MagicMock()
    col.count.return_value = 1
    col.get.return_value = {
        "ids": ["SOP-MNT-001.md::chunk::2"],
        "embeddings": [embed_vec],
    }
    return col


def _make_mock_vectorstore() -> MagicMock:
    vs = MagicMock()
    vs.similarity_search_with_relevance_scores.return_value = [
        (Document(
            page_content="SOP tool wear procedure text",
            metadata={"document_name": "SOP-MNT-001.md", "chunk_index": 2, "page_number": 0},
        ), 0.95)
    ]
    return vs


async def test_pipeline_full_run(sample_equipment_log, correlation_id):
    # Risk assessment is now handled by the rule engine — _invoke_chain is called
    # only for perception, sop_rag (query extraction), and action_plan.
    responses = iter([_PERCEPTION_DICT, _SOP_QUERY_DICT, _ACTION_PLAN_DICT])

    embed_vec = [1.0] + [0.0] * 767
    mock_col = _make_mock_col(embed_vec)
    mock_vs = _make_mock_vectorstore()
    mock_emb = MagicMock()
    mock_emb.aembed_query = AsyncMock(return_value=embed_vec)

    _mock_diagnostic = DiagnosticResult(
        equipment_id="M-12345",
        risk_index=78.9,
        risk_interpretation="HIGH",
        thresholds_checked=True,
        alert_dispatched=False,
        tool_calls=[],
        summary="Tool wear at 95% — risk index HIGH.",
    )

    with patch.object(BaseAgent, "_invoke_chain", new_callable=AsyncMock, side_effect=lambda *a, **kw: next(responses)), \
         patch.object(DiagnosticAgent, "run", new_callable=AsyncMock, return_value=_mock_diagnostic), \
         patch("agents.sop_rag_agent.get_sop_collection", return_value=mock_col), \
         patch("agents.sop_rag_agent.get_langchain_vectorstore", return_value=mock_vs), \
         patch("agents.hallucination_validator.get_sop_collection", return_value=mock_col), \
         patch("agents.hallucination_validator.get_embeddings", return_value=mock_emb):
        result = await ForgePipeline().run(sample_equipment_log, correlation_id)

    assert isinstance(result, PipelineResult)
    assert result.correlation_id == correlation_id
    assert result.risk_assessment is not None
    assert result.risk_assessment.risk_level == "WARNING"
    assert result.metrics.early_exit is False
    assert result.metrics.risk_level == "WARNING"
    assert result.anomaly_report is not None
    assert result.anomaly_report.has_anomaly is True
    assert result.anomaly_report.correlation_id == correlation_id
    assert result.action_plan is not None
    assert result.action_plan.correlation_id == correlation_id
    assert result.validation_result is not None
    assert result.validation_result.correlation_id == correlation_id
    assert result.validation_result.recommendation in ("APPROVE", "REVIEW", "REJECT")
    assert result.diagnostic_result is not None
    assert result.diagnostic_result.equipment_id == "M-12345"
    assert result.diagnostic_result.risk_index == 78.9


@pytest.mark.slow
async def test_pipeline_early_exit_on_safe(correlation_id):
    """rule engine이 SAFE를 반환하면 perception 이후 단계는 실행되지 않아야 한다."""
    # All sensors comfortably within safe range — rule engine will return SAFE
    safe_log = EquipmentLog(
        equipment_id="M-12345",
        timestamp=datetime(2026, 6, 3, 8, 0, 0, tzinfo=timezone.utc),
        readings=[
            SensorReading(sensor_id="air_temperature_k", unit="K", value=300.0),
            SensorReading(sensor_id="process_temperature_k", unit="K", value=309.0),
            SensorReading(sensor_id="rotational_speed_rpm", unit="rpm", value=2000.0),
            SensorReading(sensor_id="torque_nm", unit="Nm", value=40.0),
            SensorReading(sensor_id="tool_wear_min", unit="min", value=100.0),
        ],
        message="Normal operation",
    )

    result = await ForgePipeline().run(safe_log, correlation_id)

    assert result.risk_assessment is not None
    assert result.risk_assessment.risk_level == "SAFE"
    assert result.metrics.early_exit is True
    assert result.anomaly_report is None
    assert result.action_plan is None
    assert result.validation_result is None
    assert result.metrics.stages_completed == ["risk_assessment", "routing_gate"]


async def test_pipeline_correlation_id_propagated(sample_equipment_log):
    cid = "unique-trace-id-xyz"
    responses = iter([_PERCEPTION_DICT, _SOP_QUERY_DICT, _ACTION_PLAN_DICT])

    embed_vec = [0.5] + [0.0] * 767
    mock_col = _make_mock_col(embed_vec)
    mock_vs = _make_mock_vectorstore()
    mock_emb = MagicMock()
    mock_emb.aembed_query = AsyncMock(return_value=embed_vec)

    _mock_diagnostic = DiagnosticResult(
        equipment_id="M-12345",
        risk_index=50.0,
        risk_interpretation="MEDIUM",
        thresholds_checked=True,
        tool_calls=[],
        summary="Risk index MEDIUM.",
    )

    with patch.object(BaseAgent, "_invoke_chain", new_callable=AsyncMock, side_effect=lambda *a, **kw: next(responses)), \
         patch.object(DiagnosticAgent, "run", new_callable=AsyncMock, return_value=_mock_diagnostic), \
         patch("agents.sop_rag_agent.get_sop_collection", return_value=mock_col), \
         patch("agents.sop_rag_agent.get_langchain_vectorstore", return_value=mock_vs), \
         patch("agents.hallucination_validator.get_sop_collection", return_value=mock_col), \
         patch("agents.hallucination_validator.get_embeddings", return_value=mock_emb):
        result = await ForgePipeline().run(sample_equipment_log, cid)

    assert result.anomaly_report is not None
    assert result.anomaly_report.correlation_id == cid
    assert result.sop_context is not None
    assert result.sop_context.correlation_id == cid
    assert result.action_plan is not None
    assert result.action_plan.correlation_id == cid
    assert result.validation_result is not None
    assert result.validation_result.correlation_id == cid
