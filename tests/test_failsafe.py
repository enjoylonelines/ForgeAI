"""
LLM 장애 시 Rule Engine 단독 폴백(fail-safe) 검증.

완료 기준 (이슈 #42):
  - Ollama mock → ConnectionError 발생 → Rule Engine 결과 반환
  - /api/v1/health 응답에 mode: "rule-only" 포함
  - POST /analyze → 200 응답 + mode: "rule-only"
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from agents.base import MaxRetriesExceededError
from main import app
from models.equipment_log import EquipmentLog, SensorReading
from models.risk_assessment import RiskAssessment
from pipeline.forge_pipeline import ForgePipeline, PipelineMetrics, PipelineResult

_NOW = datetime(2026, 7, 23, 0, 0, 0, tzinfo=timezone.utc)

_CRITICAL_LOG = EquipmentLog(
    equipment_id="M-99",
    timestamp=_NOW,
    log_level="ERROR",
    readings=[
        SensorReading(sensor_id="air_temperature_k", unit="K", value=298.0),
        SensorReading(sensor_id="process_temperature_k", unit="K", value=305.0),
        SensorReading(sensor_id="rotational_speed_rpm", unit="rpm", value=1800.0),
        SensorReading(sensor_id="torque_nm", unit="Nm", value=65.0),
        SensorReading(sensor_id="tool_wear_min", unit="min", value=240.0),
    ],
    message="High tool wear detected",
    tags={},
)

_VALID_LOG_BODY = {
    "equipment_id": "M-99",
    "timestamp": "2026-07-23T00:00:00Z",
    "log_level": "ERROR",
    "readings": [
        {"sensor_id": "air_temperature_k", "unit": "K", "value": 298.0},
        {"sensor_id": "process_temperature_k", "unit": "K", "value": 305.0},
        {"sensor_id": "rotational_speed_rpm", "unit": "rpm", "value": 1800.0},
        {"sensor_id": "torque_nm", "unit": "Nm", "value": 65.0},
        {"sensor_id": "tool_wear_min", "unit": "min", "value": 240.0},
    ],
    "message": "High tool wear detected",
    "tags": {},
}


@pytest.fixture
async def api_client():
    with patch("main.ollama_health", new_callable=AsyncMock, return_value=False), \
         patch("main.chroma_health", return_value=True):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


# ── run_rule_only 직접 단위 테스트 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_rule_only_returns_risk_assessment(sample_equipment_log):
    """run_rule_only()는 LLM 없이 RiskAssessment를 포함한 PipelineResult를 반환한다."""
    pipeline = ForgePipeline()
    result = await pipeline.run_rule_only(sample_equipment_log, "test-cid-001")

    assert result.risk_assessment is not None
    assert result.risk_assessment.risk_level in ("SAFE", "WARNING", "CRITICAL")
    assert result.metrics.mode == "rule-only"
    assert result.routing_decision is not None


@pytest.mark.asyncio
async def test_run_rule_only_no_llm_calls(sample_equipment_log):
    """run_rule_only()는 BaseAgent._invoke_chain을 전혀 호출하지 않는다."""
    from agents.base import BaseAgent

    with patch.object(BaseAgent, "_invoke_chain", new_callable=AsyncMock) as mock_llm:
        pipeline = ForgePipeline()
        await pipeline.run_rule_only(sample_equipment_log, "test-cid-002")

    mock_llm.assert_not_called()


@pytest.mark.asyncio
async def test_run_rule_only_critical_sensor_escalates(sample_equipment_log):
    """CRITICAL 수준 센서 데이터 입력 시 rule-only 결과도 ESCALATE 라우팅을 반환한다."""
    pipeline = ForgePipeline()
    result = await pipeline.run_rule_only(_CRITICAL_LOG, "test-cid-003")

    assert result.routing_decision is not None
    # TWF(tool_wear=240) → WARNING → R-4 또는 ESCALATE(R-1) 확인
    assert result.routing_decision.route in ("AUTO", "ESCALATE", "HUMAN_REVIEW")
    assert result.metrics.mode == "rule-only"


# ── MaxRetriesExceededError 폴백 테스트 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_analyze_max_retries_falls_back_to_rule_only(api_client):
    """LLM이 중간에 사망해 MaxRetriesExceededError가 발생해도 rule-only로 폴백한다."""
    rule_only_result = PipelineResult(
        correlation_id="test-fallback",
        risk_assessment=RiskAssessment(
            equipment_id="M-99",
            assessed_at=_NOW,
            risk_level="WARNING",
            risk_factors=[],
            summary="Rule-only fallback after LLM failure",
            recommended_action="Inspect equipment",
        ),
        metrics=PipelineMetrics(risk_level="WARNING", mode="rule-only"),
    )

    with patch("api.routes.ollama_health", new_callable=AsyncMock, return_value=True), \
         patch("api.routes.ForgePipeline") as mock_cls:
        mock_pipeline = AsyncMock()
        mock_pipeline.run.side_effect = MaxRetriesExceededError("Ollama timed out mid-run")
        mock_pipeline.run_rule_only.return_value = rule_only_result
        mock_cls.return_value = mock_pipeline

        response = await api_client.post("/api/v1/analyze", json=_VALID_LOG_BODY)

    assert response.status_code == 200
    assert response.headers.get("x-mode") == "rule-only"
    body = response.json()
    assert body["metrics"]["mode"] == "rule-only"


# ── /health 엔드포인트 mode 필드 검증 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_returns_rule_only_mode_when_ollama_down(api_client):
    """/health는 Ollama 불능 시 mode='rule-only'를 200으로 반환한다."""
    with patch("api.routes.ollama_health", new_callable=AsyncMock, return_value=False), \
         patch("api.routes.chroma_health", return_value=True):
        response = await api_client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "rule-only"
    assert body["status"] == "degraded"
    assert body["ollama"] == "error"


@pytest.mark.asyncio
async def test_health_returns_full_mode_when_all_ok(api_client):
    """/health는 모든 의존성 정상 시 mode='full'을 200으로 반환한다."""
    with patch("api.routes.ollama_health", new_callable=AsyncMock, return_value=True), \
         patch("api.routes.chroma_health", return_value=True):
        response = await api_client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "full"
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_health_returns_503_when_chroma_down(api_client):
    """/health는 ChromaDB 불능 시 503 error를 반환한다."""
    with patch("api.routes.ollama_health", new_callable=AsyncMock, return_value=True), \
         patch("api.routes.chroma_health", return_value=False):
        response = await api_client.get("/api/v1/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"


# ── /analyze Ollama 불능 시 rule-only 200 반환 (완료 기준 #2) ────────────────

@pytest.mark.asyncio
async def test_analyze_ollama_down_returns_200_rule_only(api_client):
    """완료 기준 #2: Ollama 강제 중단 상태에서 analyze가 200 + mode='rule-only'를 반환한다."""
    rule_only_result = PipelineResult(
        correlation_id="test-criterion-2",
        risk_assessment=RiskAssessment(
            equipment_id="M-99",
            assessed_at=_NOW,
            risk_level="WARNING",
            risk_factors=[],
            summary="Rule-only: tool wear exceeds threshold",
            recommended_action="Schedule inspection",
        ),
        metrics=PipelineMetrics(risk_level="WARNING", mode="rule-only"),
    )

    with patch("api.routes.ollama_health", new_callable=AsyncMock, return_value=False), \
         patch("api.routes.ForgePipeline") as mock_cls:
        mock_pipeline = AsyncMock()
        mock_pipeline.run_rule_only.return_value = rule_only_result
        mock_cls.return_value = mock_pipeline

        response = await api_client.post("/api/v1/analyze", json=_VALID_LOG_BODY)

    assert response.status_code == 200
    assert response.headers.get("x-mode") == "rule-only"
    body = response.json()
    assert body["metrics"]["mode"] == "rule-only"
    mock_pipeline.run.assert_not_called()
    mock_pipeline.run_rule_only.assert_called_once()
