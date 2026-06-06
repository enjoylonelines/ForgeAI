from __future__ import annotations

import pytest

from agents.base import MaxRetriesExceededError
from agents.intent_extraction_agent import IntentExtractionAgent

_VALID_INTENT = {
    "equipment_id": "M-12345",
    "symptom_description": "기계에서 이상한 소리가 납니다",
    "sensor_types": ["tool_wear_min", "torque_nm"],
    "urgency": "high",
    "failure_type_hints": ["TWF"],
}


async def test_intent_extraction_success(mock_ollama_chat, correlation_id):
    """정상 응답에서 ExtractedIntent 필드가 올바르게 매핑된다."""
    mock_ollama_chat.return_value = _VALID_INTENT
    agent = IntentExtractionAgent()
    result = await agent.run("기계에서 이상한 소리가 납니다", correlation_id=correlation_id)

    assert result.equipment_id == "M-12345"
    assert result.urgency == "high"
    assert "TWF" in result.failure_type_hints
    assert "tool_wear_min" in result.sensor_types
    assert result.symptom_description == "기계에서 이상한 소리가 납니다"


async def test_intent_extraction_equipment_id_override(mock_ollama_chat, correlation_id):
    """equipment_id_override는 LLM 반환값보다 우선 적용된다."""
    mock_ollama_chat.return_value = {**_VALID_INTENT, "equipment_id": "M-99999"}
    agent = IntentExtractionAgent()
    result = await agent.run(
        "기계에서 이상한 소리가 납니다",
        equipment_id_override="M-12345",
        correlation_id=correlation_id,
    )

    assert result.equipment_id == "M-12345"


async def test_intent_extraction_max_retries_propagated(mock_ollama_chat, correlation_id):
    """Ollama 재시도 초과 시 MaxRetriesExceededError가 그대로 전파된다."""
    mock_ollama_chat.side_effect = MaxRetriesExceededError("chain failed after retries")
    agent = IntentExtractionAgent()
    with pytest.raises(MaxRetriesExceededError):
        await agent.run("소리가 이상해요", correlation_id=correlation_id)


async def test_intent_extraction_defaults_on_missing_fields(mock_ollama_chat, correlation_id):
    """LLM 응답에 선택 필드가 빠진 경우 기본값이 채워진다."""
    mock_ollama_chat.return_value = {"symptom_description": "vibration detected"}
    agent = IntentExtractionAgent()
    result = await agent.run("vibration detected", correlation_id=correlation_id)

    assert result.urgency == "medium"
    assert result.sensor_types == []
    assert result.failure_type_hints == []
    assert result.equipment_id is None
    assert result.symptom_description == "vibration detected"
