"""라벨 누수 차단 — LLM 프롬프트에 정답 라벨 문자열이 포함되지 않는지 검증."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, call

import pytest

from agents.base import BaseAgent
from agents.perception_agent import PerceptionAgent
from agents.sop_rag_agent import SOPRAGAgent
from models.anomaly_report import AnomalyDetail, AnomalyReport
from models.equipment_log import EquipmentLog, SensorReading

_NOW = datetime(2026, 6, 3, 8, 0, 0, tzinfo=timezone.utc)
_CID = "test-cid"

_FAILURE_LABELS = {"TWF", "HDF", "PWF", "OSF", "RNF", "failure_types", "Machine failure detected"}

_LOG_WITH_LABELS = EquipmentLog(
    equipment_id="M-99",
    timestamp=_NOW,
    log_level="ERROR",
    readings=[
        SensorReading(sensor_id="tool_wear_min", unit="min", value=220.0),
        SensorReading(sensor_id="torque_nm", unit="Nm", value=55.0),
    ],
    message="Machine failure detected: TWF, HDF",
    tags={"machine_type": "L", "failure_types": "TWF,HDF"},
)

_ANOMALY_REPORT_WITH_LABELS = AnomalyReport(
    equipment_id="M-99",
    timestamp=_NOW,
    has_anomaly=True,
    anomalies=[
        AnomalyDetail(
            sensor_id="tool_wear_min",
            observed_value=220.0,
            expected_range=(0.0, 200.0),
            severity="HIGH",
            description="Tool wear exceeds threshold",
        )
    ],
    summary="High tool wear on M-99",
    raw_log_snippet='{"tool_wear_min": 220.0}',
    tags={"machine_type": "L", "failure_types": "TWF,HDF"},
    correlation_id=_CID,
)

_VALID_PERCEPTION_RESPONSE = {
    "equipment_id": "M-99",
    "timestamp": _NOW.isoformat(),
    "has_anomaly": True,
    "anomalies": [
        {
            "sensor_id": "tool_wear_min",
            "observed_value": 220.0,
            "expected_range": [0, 200],
            "severity": "HIGH",
            "description": "Excessive tool wear",
        }
    ],
    "summary": "Tool wear anomaly",
    "raw_log_snippet": '{"tool_wear_min": 220.0}',
}

_VALID_SOP_RESPONSE = {"query": "tool wear replacement procedure CNC"}


def _labels_in(text: str) -> list[str]:
    return [label for label in _FAILURE_LABELS if label in text]


async def test_perception_prompt_excludes_labels():
    captured: list[str] = []

    async def fake_invoke(user_msg: str, cid):
        captured.append(user_msg)
        return _VALID_PERCEPTION_RESPONSE

    with patch.object(BaseAgent, "_invoke_chain", side_effect=fake_invoke):
        agent = PerceptionAgent()
        await agent.run(_LOG_WITH_LABELS, _CID)

    assert captured, "invoke_chain was never called"
    prompt_text = captured[0]
    leaked = _labels_in(prompt_text)
    assert not leaked, f"라벨이 프롬프트에 누출됨: {leaked}\n--- prompt ---\n{prompt_text}"


async def test_perception_prompt_includes_sensor_readings():
    """화이트리스트 필드가 프롬프트에 포함되는지 확인."""
    captured: list[str] = []

    async def fake_invoke(user_msg: str, cid):
        captured.append(user_msg)
        return _VALID_PERCEPTION_RESPONSE

    with patch.object(BaseAgent, "_invoke_chain", side_effect=fake_invoke):
        agent = PerceptionAgent()
        await agent.run(_LOG_WITH_LABELS, _CID)

    prompt_text = captured[0]
    assert "tool_wear_min" in prompt_text
    assert "220" in prompt_text
    assert "M-99" in prompt_text


async def test_sop_rag_prompt_excludes_labels(mock_chroma_collection):
    captured: list[str] = []

    async def fake_invoke(user_msg: str, cid):
        captured.append(user_msg)
        return _VALID_SOP_RESPONSE

    with patch.object(BaseAgent, "_invoke_chain", side_effect=fake_invoke):
        agent = SOPRAGAgent()
        await agent.run(_ANOMALY_REPORT_WITH_LABELS, failure_type="TWF", correlation_id=_CID)

    assert captured, "invoke_chain was never called"
    prompt_text = captured[0]
    leaked = _labels_in(prompt_text)
    assert not leaked, f"라벨이 SOP 프롬프트에 누출됨: {leaked}\n--- prompt ---\n{prompt_text}"


async def test_stream_simulator_path_excludes_labels():
    """stream_simulator 경로: model_dump() 전송 후 API에서 perception까지 라벨 미노출."""
    captured: list[str] = []

    async def fake_invoke(user_msg: str, cid):
        captured.append(user_msg)
        return _VALID_PERCEPTION_RESPONSE

    payload = _LOG_WITH_LABELS.model_dump(mode="json")
    reconstructed_log = EquipmentLog.model_validate(payload)

    with patch.object(BaseAgent, "_invoke_chain", side_effect=fake_invoke):
        agent = PerceptionAgent()
        await agent.run(reconstructed_log, _CID)

    prompt_text = captured[0]
    leaked = _labels_in(prompt_text)
    assert not leaked, f"stream_simulator 경로에서 라벨 누출: {leaked}"
