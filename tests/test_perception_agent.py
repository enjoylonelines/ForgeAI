from __future__ import annotations

import pytest

from agents.base import MaxRetriesExceededError, ParseOutputError
from agents.perception_agent import PerceptionAgent
from models.equipment_log import EquipmentLog, SensorReading

_NOW_ISO = "2026-06-03T08:00:00+00:00"

_VALID_DICT = {
    "equipment_id": "M-12345",
    "timestamp": _NOW_ISO,
    "has_anomaly": True,
    "anomalies": [
        {
            "sensor_id": "tool_wear_min",
            "observed_value": 216.0,
            "expected_range": [0, 200],
            "severity": "HIGH",
            "description": "Tool wear exceeds safe threshold",
        }
    ],
    "summary": "Tool wear failure risk on M-12345",
    "raw_log_snippet": '{"tool_wear_min": 216.0}',
}


async def test_perception_agent_success(mock_ollama_chat, sample_equipment_log, correlation_id):
    mock_ollama_chat.return_value = _VALID_DICT
    agent = PerceptionAgent()
    report = await agent.run(sample_equipment_log, correlation_id)

    assert report.has_anomaly is True
    assert len(report.anomalies) == 1
    assert report.anomalies[0].sensor_id == "tool_wear_min"
    assert report.correlation_id == correlation_id


async def test_perception_agent_no_anomaly(mock_ollama_chat, correlation_id):
    from datetime import datetime, timezone
    normal_log = EquipmentLog(
        equipment_id="M-00001",
        timestamp=datetime(2026, 6, 3, 8, 0, 0, tzinfo=timezone.utc),
        log_level="INFO",
        readings=[SensorReading(sensor_id="tool_wear_min", unit="min", value=50.0)],
        message="Normal operation",
    )
    mock_ollama_chat.return_value = {
        "equipment_id": "M-00001",
        "timestamp": _NOW_ISO,
        "has_anomaly": False,
        "anomalies": [],
        "summary": "All systems normal",
        "raw_log_snippet": '{"tool_wear_min": 50.0}',
    }
    agent = PerceptionAgent()
    report = await agent.run(normal_log, correlation_id)

    assert report.has_anomaly is False
    assert report.anomalies == []


async def test_perception_agent_max_retries_exceeded(mock_ollama_chat, sample_equipment_log, correlation_id):
    mock_ollama_chat.side_effect = MaxRetriesExceededError("chain failed after retries")
    agent = PerceptionAgent()
    with pytest.raises(MaxRetriesExceededError):
        await agent.run(sample_equipment_log, correlation_id)


async def test_perception_agent_parse_error(mock_ollama_chat, sample_equipment_log, correlation_id):
    mock_ollama_chat.return_value = {"unexpected": "structure"}
    agent = PerceptionAgent()
    with pytest.raises(ParseOutputError):
        await agent.run(sample_equipment_log, correlation_id)


async def test_perception_agent_tags_propagated(mock_ollama_chat, sample_equipment_log, correlation_id):
    mock_ollama_chat.return_value = _VALID_DICT
    agent = PerceptionAgent()
    report = await agent.run(sample_equipment_log, correlation_id)

    assert report.tags == sample_equipment_log.tags
    assert report.tags.get("failure_types") == "TWF"
