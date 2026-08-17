"""DecisionEvent JSONL 계측 — 스키마·라이터·파이프라인 노드·추적 가능률 검증."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from models.action_plan import ActionPlan, ActionStep
from models.anomaly_report import AnomalyDetail, AnomalyReport
from models.decision_event import DecisionEvent
from models.equipment_log import EquipmentLog, SensorReading
from models.risk_assessment import RiskAssessment
from models.sop_context import SOPChunk, SOPContext
from models.validation_result import ValidationResult

_NOW = datetime(2026, 6, 3, 8, 0, 0, tzinfo=timezone.utc)
_CID = "trace-test-001"

_LOG = EquipmentLog(
    equipment_id="M-01",
    timestamp=_NOW,
    log_level="ERROR",
    readings=[SensorReading(sensor_id="tool_wear_min", unit="min", value=220.0)],
    message="Machine failure detected: TWF",
    tags={"machine_type": "M", "failure_types": "TWF"},
)


def _risk(level: str) -> RiskAssessment:
    return RiskAssessment(
        equipment_id="M-01",
        assessed_at=_NOW,
        risk_level=level,
        failure_type="TWF" if level != "SAFE" else "NONE",
        triggered_failure_types=["TWF"] if level != "SAFE" else [],
        risk_factors=[],
        summary=f"risk_level={level}",
    )


def _anomaly(has_anomaly: bool) -> AnomalyReport:
    return AnomalyReport(
        equipment_id="M-01", timestamp=_NOW,
        has_anomaly=has_anomaly,
        anomalies=[AnomalyDetail(sensor_id="tool_wear_min", observed_value=220.0, severity="HIGH", description="wear")] if has_anomaly else [],
        summary="test", raw_log_snippet="", tags={}, correlation_id=_CID,
    )


def _sop() -> SOPContext:
    return SOPContext(
        equipment_id="M-01", query_used="wear",
        chunks=[SOPChunk(chunk_id="doc::0", document_name="doc", text="SOP", relevance_score=0.9)],
        correlation_id=_CID,
    )


def _plan() -> ActionPlan:
    return ActionPlan(
        equipment_id="M-01", generated_at=_NOW,
        steps=[ActionStep(step_number=1, action="Stop", responsible_role="tech", priority="P1", estimated_duration_minutes=5, sop_reference="doc::0")],
        escalation_required=False, correlation_id=_CID,
    )


def _validation(rec: str) -> ValidationResult:
    return ValidationResult(
        equipment_id="M-01", validated_at=_NOW,
        overall_grounding_score=0.9, is_valid=True,
        step_validations=[], ungrounded_steps=[],
        recommendation=rec, explanation="ok", correlation_id=_CID,
    )


# ── 스키마 ─────────────────────────────────────────────────────────────────────

def test_decision_event_schema():
    event = DecisionEvent(
        correlation_id="cid-1",
        stage="rule_engine",
        signals={"risk_level": "CRITICAL"},
        decision="CRITICAL",
        reason="tool_wear > 200",
        duration_ms=12.5,
    )
    assert event.policy_version == "pipeline-v1"
    assert isinstance(event.ts, datetime)
    data = json.loads(event.model_dump_json())
    assert data["stage"] == "rule_engine"
    assert data["duration_ms"] == 12.5


# ── JSONL 라이터 ────────────────────────────────────────────────────────────────

def test_decision_logger_appends_jsonl(tmp_path, monkeypatch):
    from core import decision_logger

    path = str(tmp_path / "test.jsonl")
    monkeypatch.setenv("DECISION_LOG_PATH", path)

    decision_logger.append(DecisionEvent(correlation_id="c1", stage="rule_engine", signals={}, decision="SAFE", reason="ok", duration_ms=1.0))
    decision_logger.append(DecisionEvent(correlation_id="c1", stage="perception", signals={}, decision="NO_ANOMALY", reason="clean", duration_ms=2.0))

    lines = [json.loads(ln) for ln in open(path).read().splitlines() if ln.strip()]
    assert len(lines) == 2
    assert lines[0]["stage"] == "rule_engine"
    assert lines[1]["stage"] == "perception"


def test_decision_logger_creates_directory(tmp_path, monkeypatch):
    from core import decision_logger

    path = str(tmp_path / "nested" / "dir" / "decisions.jsonl")
    monkeypatch.setenv("DECISION_LOG_PATH", path)
    decision_logger.append(DecisionEvent(correlation_id="c1", stage="rule_engine", signals={}, decision="SAFE", reason="ok", duration_ms=1.0))

    assert os.path.exists(path)


# ── 파이프라인 노드 단위 계측 ────────────────────────────────────────────────────

async def test_node_risk_assessment_records_event():
    """_node_risk_assessment가 rule_engine + ml_predictor DecisionEvent를 기록한다."""
    import core.decision_logger as dl
    from pipeline.forge_pipeline import ForgePipeline, _GraphState

    captured: list[DecisionEvent] = []
    pipeline = ForgePipeline.__new__(ForgePipeline)

    with patch("pipeline.forge_pipeline.assess_risk", return_value=_risk("CRITICAL")), \
         patch("pipeline.forge_pipeline.ml_predictor.predict_proba", return_value=0.05), \
         patch.object(dl, "append", side_effect=captured.append):
        state = _GraphState(log=_LOG, correlation_id=_CID)
        await pipeline._node_risk_assessment(state)

    stages = {e.stage for e in captured}
    assert "rule_engine" in stages
    assert "ml_predictor" in stages
    rule_event = next(e for e in captured if e.stage == "rule_engine")
    assert rule_event.decision == "CRITICAL"
    assert rule_event.correlation_id == _CID


async def test_node_perception_records_event(mock_ollama_chat):
    """_node_perception이 perception DecisionEvent를 기록한다."""
    import core.decision_logger as dl
    from pipeline.forge_pipeline import ForgePipeline, _GraphState

    mock_ollama_chat.return_value = {
        "equipment_id": "M-01", "timestamp": _NOW.isoformat(),
        "has_anomaly": True, "anomalies": [{"sensor_id": "tool_wear_min", "observed_value": 220.0, "expected_range": [0, 200], "severity": "HIGH", "description": "wear"}],
        "summary": "High wear", "raw_log_snippet": "{}",
    }
    captured: list[DecisionEvent] = []
    pipeline = ForgePipeline.__new__(ForgePipeline)
    from agents.perception_agent import PerceptionAgent
    pipeline._perception = PerceptionAgent()

    with patch.object(dl, "append", side_effect=captured.append):
        state = _GraphState(log=_LOG, correlation_id=_CID)
        await pipeline._node_perception(state)

    assert any(e.stage == "perception" for e in captured)
    perception_event = next(e for e in captured if e.stage == "perception")
    assert perception_event.decision == "ANOMALY_DETECTED"


async def test_node_validator_records_event(mock_ollama_chat, sample_action_plan, sample_sop_context):
    """_node_validator가 validator DecisionEvent를 기록한다."""
    import core.decision_logger as dl
    from pipeline.forge_pipeline import ForgePipeline, _GraphState
    from agents.hallucination_validator import HallucinationValidatorAgent

    captured: list[DecisionEvent] = []
    pipeline = ForgePipeline.__new__(ForgePipeline)

    with patch.object(HallucinationValidatorAgent, "run", new=AsyncMock(return_value=_validation("APPROVE"))), \
         patch.object(dl, "append", side_effect=captured.append):
        pipeline._validator = HallucinationValidatorAgent()
        state = _GraphState(log=_LOG, correlation_id=_CID, action_plan=sample_action_plan, sop_context=sample_sop_context)
        await pipeline._node_validator(state)

    assert any(e.stage == "validator" for e in captured)
    v_event = next(e for e in captured if e.stage == "validator")
    assert v_event.decision == "APPROVE"


def test_route_after_risk_records_routing_event():
    """_route_after_risk가 routing DecisionEvent를 기록한다."""
    import core.decision_logger as dl
    from pipeline.forge_pipeline import ForgePipeline, _GraphState

    captured: list[DecisionEvent] = []
    pipeline = ForgePipeline.__new__(ForgePipeline)
    state = _GraphState(log=_LOG, correlation_id=_CID, risk_assessment=_risk("SAFE"))

    with patch.object(dl, "append", side_effect=captured.append):
        result = pipeline._route_after_risk(state)

    assert result == "early_exit"
    assert len(captured) == 1
    assert captured[0].stage == "routing"
    assert captured[0].decision == "early_exit"


def test_route_after_perception_records_routing_event():
    import core.decision_logger as dl
    from pipeline.forge_pipeline import ForgePipeline, _GraphState

    captured: list[DecisionEvent] = []
    pipeline = ForgePipeline.__new__(ForgePipeline)
    state = _GraphState(log=_LOG, correlation_id=_CID, anomaly_report=_anomaly(True))

    with patch.object(dl, "append", side_effect=captured.append):
        result = pipeline._route_after_perception(state)

    assert result == "parallel"
    assert captured[0].stage == "routing"
    assert captured[0].decision == "parallel"


def test_route_after_validator_records_routing_event():
    import core.decision_logger as dl
    from pipeline.forge_pipeline import ForgePipeline, _GraphState

    captured: list[DecisionEvent] = []
    pipeline = ForgePipeline.__new__(ForgePipeline)
    state = _GraphState(log=_LOG, correlation_id=_CID, validation_result=_validation("APPROVE"), retry_count=0)

    with patch.object(dl, "append", side_effect=captured.append):
        result = pipeline._route_after_validator(state)

    assert result == "end_approved"
    assert captured[0].stage == "routing"
    assert captured[0].decision == "end_approved"


# ── 추적 가능률 스크립트 ─────────────────────────────────────────────────────────

def test_check_traceability_all_stages_present(tmp_path):
    from scripts.check_traceability import check

    path = str(tmp_path / "decisions.jsonl")
    events = (
        [{"correlation_id": "cid-x", "stage": s} for s in ["rule_engine", "perception", "sop_search", "action_plan", "validator"]]
        + [{"correlation_id": "cid-x", "stage": "routing", "decision": f"node_{i}"} for i in range(3)]
    )
    with open(path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    assert check(path) == 0


def test_check_traceability_missing_stage_returns_1(tmp_path):
    from scripts.check_traceability import check

    path = str(tmp_path / "decisions.jsonl")
    events = [{"correlation_id": "cid-x", "stage": s} for s in ["rule_engine", "perception"]]
    with open(path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    assert check(path) == 1
