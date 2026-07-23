from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from agents.base import MaxRetriesExceededError, ParseOutputError
from main import app
from models.risk_assessment import RiskAssessment
from models.validation_result import ValidationResult
from pipeline.forge_pipeline import PipelineMetrics, PipelineResult

_VALID_LOG_BODY = {
    "equipment_id": "M-12345",
    "timestamp": "2026-06-06T00:00:00Z",
    "log_level": "ERROR",
    "readings": [{"sensor_id": "tool_wear_min", "unit": "min", "value": 216.0}],
    "message": "Machine failure detected",
    "tags": {},
}

_VALID_QUERY_BODY = {
    "query": "기계에서 이상한 소리가 납니다",
    "equipment_id": None,
}

_VALID_CONTROL_BODY = {
    "dry_run": True,
    "action_plan": {
        "equipment_id": "M-12345",
        "generated_at": "2026-06-06T00:00:00Z",
        "steps": [
            {
                "step_number": 1,
                "action": "Stop machine immediately",
                "responsible_role": "maintenance_technician",
                "priority": "P1",
                "estimated_duration_minutes": 5,
                "sop_reference": "SOP-MNT-001.md::chunk::2",
            }
        ],
        "escalation_required": False,
        "escalation_reason": None,
    },
}


@pytest.fixture
async def api_client():
    """lifespan 헬스 체크를 mock하고 AsyncClient를 제공한다."""
    with patch("main.ollama_health", new_callable=AsyncMock, return_value=True), \
         patch("main.chroma_health", return_value=True):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


def _make_pipeline_result(recommendation: str) -> PipelineResult:
    now = datetime.now(timezone.utc)
    validation = ValidationResult(
        equipment_id="M-12345",
        validated_at=now,
        overall_grounding_score=0.50 if recommendation == "REJECT" else 0.70,
        is_valid=recommendation == "APPROVE",
        recommendation=recommendation,
        correlation_id="test-cid",
    )
    return PipelineResult(
        correlation_id="test-cid",
        validation_result=validation,
        metrics=PipelineMetrics(risk_level="WARNING"),
    )


# ── /analyze 에러 핸들링 ────────────────────────────────────────────────────────

async def test_analyze_llm_unavailable_falls_back_to_rule_only(api_client):
    """/analyze에서 Ollama 연결 실패 시 rule-only 폴백으로 200을 반환한다."""
    rule_only_result = PipelineResult(
        correlation_id="test-cid",
        risk_assessment=RiskAssessment(
            equipment_id="M-12345",
            assessed_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
            risk_level="WARNING",
            risk_factors=[],
            summary="Rule-only fallback",
            recommended_action="Inspect equipment",
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


async def test_analyze_parse_error_returns_422(api_client):
    """/analyze에서 LLM 출력 파싱 실패 시 422를 반환한다."""
    with patch("api.routes.ForgePipeline") as mock_cls:
        mock_pipeline = AsyncMock()
        mock_pipeline.run.side_effect = ParseOutputError("unexpected JSON structure")
        mock_cls.return_value = mock_pipeline
        response = await api_client.post("/api/v1/analyze", json=_VALID_LOG_BODY)

    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["error"] == "parse_error"


async def test_analyze_invalid_body_returns_422(api_client):
    """/analyze에 필수 필드 누락 시 422를 반환한다."""
    response = await api_client.post("/api/v1/analyze", json={"equipment_id": "M-1"})
    assert response.status_code == 422


async def test_analyze_reject_sets_header(api_client):
    """validation recommendation이 REJECT이면 X-Plan-Status: REJECTED 헤더가 설정된다."""
    with patch("api.routes.ForgePipeline") as mock_cls:
        mock_pipeline = AsyncMock()
        mock_pipeline.run.return_value = _make_pipeline_result("REJECT")
        mock_cls.return_value = mock_pipeline
        response = await api_client.post("/api/v1/analyze", json=_VALID_LOG_BODY)

    assert response.status_code == 200
    assert response.headers.get("x-plan-status") == "REJECTED"


async def test_analyze_review_sets_header(api_client):
    """validation recommendation이 REVIEW이면 X-Plan-Status: REVIEW 헤더가 설정된다."""
    with patch("api.routes.ForgePipeline") as mock_cls:
        mock_pipeline = AsyncMock()
        mock_pipeline.run.return_value = _make_pipeline_result("REVIEW")
        mock_cls.return_value = mock_pipeline
        response = await api_client.post("/api/v1/analyze", json=_VALID_LOG_BODY)

    assert response.status_code == 200
    assert response.headers.get("x-plan-status") == "REVIEW"


async def test_analyze_approve_has_no_status_header(api_client):
    """validation recommendation이 APPROVE이면 X-Plan-Status 헤더가 없다."""
    with patch("api.routes.ForgePipeline") as mock_cls:
        mock_pipeline = AsyncMock()
        mock_pipeline.run.return_value = _make_pipeline_result("APPROVE")
        mock_cls.return_value = mock_pipeline
        response = await api_client.post("/api/v1/analyze", json=_VALID_LOG_BODY)

    assert response.status_code == 200
    assert "x-plan-status" not in response.headers


# ── /diagnose 에러 핸들링 ──────────────────────────────────────────────────────

async def test_diagnose_llm_unavailable_returns_503(api_client):
    """/diagnose에서 Ollama 연결 실패 시 503을 반환한다."""
    with patch("api.routes.NLDiagnosisPipeline") as mock_cls:
        mock_pipeline = AsyncMock()
        mock_pipeline.run.side_effect = MaxRetriesExceededError("Ollama timeout")
        mock_cls.return_value = mock_pipeline
        response = await api_client.post("/api/v1/diagnose", json=_VALID_QUERY_BODY)

    assert response.status_code == 503
    body = response.json()
    assert body["detail"]["error"] == "llm_unavailable"


async def test_diagnose_invalid_body_returns_422(api_client):
    """/diagnose에 query 필드 누락 시 422를 반환한다."""
    response = await api_client.post("/api/v1/diagnose", json={"equipment_id": "M-1"})
    assert response.status_code == 422


# ── /control/plan 에러 핸들링 ──────────────────────────────────────────────────

async def test_control_plan_returns_dry_run_result(api_client):
    """C++ 산업제어 어댑터 결과를 API 응답으로 반환한다."""
    with patch("api.routes.execute_control_plan") as execute:
        execute.return_value = {
            "correlation_id": "cid-001",
            "dry_run": True,
            "command_count": 1,
            "results": [
                {
                    "equipment_id": "M-12345",
                    "command_type": "STOP_MACHINE",
                    "status": "accepted",
                    "dry_run": True,
                    "adapter": "cpp-control-adapter-v1",
                    "message": "Dry-run accepted STOP_MACHINE",
                    "correlation_id": "cid-001",
                }
            ],
            "safety_note": "C++ adapter is wired in dry-run mode only; no PLC or actuator is modified.",
        }
        response = await api_client.post("/api/v1/control/plan", json=_VALID_CONTROL_BODY)

    assert response.status_code == 200
    body = response.json()
    assert body["command_count"] == 1
    assert body["results"][0]["adapter"] == "cpp-control-adapter-v1"


# ── /health 에러 핸들링 ────────────────────────────────────────────────────────

async def test_health_degraded_when_ollama_down(api_client):
    """/health에서 Ollama 불능 시 status=degraded, mode=rule-only, 200을 반환한다.
    rule-only 폴백으로 요청을 처리할 수 있으므로 readiness probe는 통과(200)한다."""
    with patch("api.routes.ollama_health", new_callable=AsyncMock, return_value=False), \
         patch("api.routes.chroma_health", return_value=True), \
         patch("api.routes.get_sop_collection") as mock_col:
        mock_col.return_value.count.return_value = 5
        response = await api_client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["mode"] == "rule-only"
    assert body["ollama"] == "error"
    assert body["chromadb"] == "ok"


async def test_health_ok_when_all_services_up(api_client):
    """/health에서 모든 서비스 정상 시 status ok, 200을 반환한다."""
    with patch("api.routes.ollama_health", new_callable=AsyncMock, return_value=True), \
         patch("api.routes.chroma_health", return_value=True), \
         patch("api.routes.get_sop_collection") as mock_col:
        mock_col.return_value.count.return_value = 10
        response = await api_client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["collection_doc_count"] == 10
