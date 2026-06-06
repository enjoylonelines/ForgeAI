from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from agents.diagnostic_agent import DiagnosticAgent


@pytest.fixture
def mock_diagnostic_llm():
    """DiagnosticAgent의 LLM bind_tools 결과를 mock — Ollama 호출 없이 테스트."""
    with patch("agents.diagnostic_agent.get_chat_llm") as mock_get_llm, \
         patch("agents.diagnostic_agent.get_current_trace", return_value=None):
        mock_llm_instance = MagicMock()
        bound_llm = MagicMock()
        bound_llm.ainvoke = AsyncMock()
        mock_llm_instance.bind_tools.return_value = bound_llm
        mock_get_llm.return_value = mock_llm_instance
        yield bound_llm


async def test_diagnostic_agent_full_tool_sequence(
    mock_diagnostic_llm, sample_anomaly_report, correlation_id
):
    """thresholds → risk_index → alert 3단계 도구 호출 후 최종 요약을 반환한다."""
    mock_diagnostic_llm.ainvoke.side_effect = [
        AIMessage(content="", tool_calls=[
            {"name": "get_sensor_thresholds", "args": {"equipment_type": "M"}, "id": "tc1", "type": "tool_call"},
            {"name": "calculate_risk_index", "args": {"tool_wear_min": 216.0, "torque_nm": 42.8, "rotational_speed_rpm": 1251.0}, "id": "tc2", "type": "tool_call"},
            {"name": "alert_maintenance_team", "args": {"equipment_id": "M-12345", "severity": "CRITICAL", "message": "Tool wear exceeds threshold"}, "id": "tc3", "type": "tool_call"},
        ]),
        AIMessage(
            content="Tool wear at 216 min exceeds threshold. Risk index HIGH. Alert dispatched.",
            tool_calls=[],
        ),
    ]
    agent = DiagnosticAgent()
    result = await agent.run(sample_anomaly_report, correlation_id)

    assert result.equipment_id == "M-12345"
    assert result.thresholds_checked is True
    assert result.risk_index is not None
    assert result.alert_dispatched is True
    assert result.alert_id is not None
    assert len(result.tool_calls) == 3
    assert "Tool wear" in result.summary


async def test_diagnostic_agent_no_alert_when_low_risk(
    mock_diagnostic_llm, sample_anomaly_report, correlation_id
):
    """risk_index가 낮으면 alert_maintenance_team 호출 없이 종료된다."""
    mock_diagnostic_llm.ainvoke.side_effect = [
        AIMessage(content="", tool_calls=[
            {"name": "get_sensor_thresholds", "args": {"equipment_type": "M"}, "id": "tc1", "type": "tool_call"},
            {"name": "calculate_risk_index", "args": {"tool_wear_min": 50.0, "torque_nm": 20.0, "rotational_speed_rpm": 1400.0}, "id": "tc2", "type": "tool_call"},
        ]),
        AIMessage(content="Risk index LOW. No alert dispatched.", tool_calls=[]),
    ]
    agent = DiagnosticAgent()
    result = await agent.run(sample_anomaly_report, correlation_id)

    assert result.thresholds_checked is True
    assert result.risk_index is not None
    assert result.alert_dispatched is False
    assert result.alert_id is None
    assert len(result.tool_calls) == 2


async def test_diagnostic_agent_no_tool_calls(
    mock_diagnostic_llm, sample_anomaly_report, correlation_id
):
    """LLM이 도구 없이 바로 텍스트 응답하면 tool_calls가 빈 리스트로 반환된다."""
    mock_diagnostic_llm.ainvoke.return_value = AIMessage(
        content="No abnormal conditions detected from sensor readings.",
        tool_calls=[],
    )
    agent = DiagnosticAgent()
    result = await agent.run(sample_anomaly_report, correlation_id)

    assert result.tool_calls == []
    assert result.thresholds_checked is False
    assert result.alert_dispatched is False
    assert result.summary == "No abnormal conditions detected from sensor readings."


async def test_diagnostic_agent_unknown_tool_name_records_error(
    mock_diagnostic_llm, sample_anomaly_report, correlation_id
):
    """미등록 도구 이름이 오면 error를 output에 기록하고 루프를 계속 진행한다."""
    mock_diagnostic_llm.ainvoke.side_effect = [
        AIMessage(content="", tool_calls=[
            {"name": "nonexistent_tool", "args": {}, "id": "tc1", "type": "tool_call"},
        ]),
        AIMessage(content="Completed despite unknown tool.", tool_calls=[]),
    ]
    agent = DiagnosticAgent()
    result = await agent.run(sample_anomaly_report, correlation_id)

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].tool_name == "nonexistent_tool"
    assert "error" in result.tool_calls[0].output
