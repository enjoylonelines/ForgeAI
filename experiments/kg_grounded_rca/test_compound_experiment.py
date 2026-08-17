from __future__ import annotations

from datetime import datetime, timezone

from core.rule_engine import assess_risk
from models.equipment_log import EquipmentLog, SensorReading
from run_compound_experiment import score_response


def _grounded_response() -> dict:
    return {
        "scenario_id": "twf-osf-compound-001",
        "diagnosis": {
            "primary_failure_mode": "OSF",
            "contributing_failure_modes": ["TWF"],
            "root_cause": "공구 수명 초과가 절삭 저항과 복합 오버스트레인을 유발",
            "causal_chain": [
                {
                    "statement": "공구 마모가 TWF를 유발한다.",
                    "evidence_ids": ["G6"],
                },
                {
                    "statement": "TWF의 절삭 저항 증가가 OSF에 기여한다.",
                    "evidence_ids": ["G8", "G9"],
                },
            ],
            "confidence": 0.95,
        },
        "action_plan": [
            {
                "step_number": 1,
                "action": "Feed Hold로 이송 정지 후 안전 위치에서 스핀들을 정지한다.",
                "evidence_ids": ["O1"],
            },
            {
                "step_number": 2,
                "action": "공구 파손과 스핀들 런아웃, 클램프를 검사한다.",
                "evidence_ids": ["O2"],
            },
            {
                "step_number": 3,
                "action": "새 공구로 교체하고 오프셋과 수명 카운터를 재설정한다.",
                "evidence_ids": ["O4", "T2"],
            },
            {
                "step_number": 4,
                "action": "이송 속도를 15-25% 줄이고 절삭 조건을 검토한다.",
                "evidence_ids": ["O3"],
            },
            {
                "step_number": 5,
                "action": "공절삭과 30% 시험 운전 후 품질 검사하고 감독자 승인 후 복귀한다.",
                "evidence_ids": ["O5", "T3", "T4"],
            },
        ],
        "claims": [
            {
                "claim": "공구 마모가 절삭 저항을 높여 OSF에 기여한다.",
                "evidence_ids": ["G6", "G8", "G9"],
            }
        ],
        "uncertainties": [],
    }


def test_multi_path_response_passes_and_covers_both_sops() -> None:
    score = score_response("multi_path_kg_sop", _grounded_response())

    assert score["pass_rate"] == 1.0
    assert score["cross_sop_coverage"] is True


def test_single_label_rejects_twf_evidence_ids() -> None:
    score = score_response("single_label_osf", _grounded_response())

    assert "G6" in score["invalid_evidence_ids"]
    assert "T2" in score["invalid_evidence_ids"]
    assert score["checks"]["no_invalid_evidence_ids"] is False


def test_missing_twf_contributor_is_detected() -> None:
    response = _grounded_response()
    response["diagnosis"]["contributing_failure_modes"] = []

    score = score_response("multi_path_kg_sop", response)

    assert score["checks"]["detects_twf_contributor"] is False


def test_live_rule_engine_selects_osf_but_preserves_twf() -> None:
    log = EquipmentLog(
        equipment_id="CNC-02",
        timestamp=datetime(2026, 7, 26, tzinfo=timezone.utc),
        readings=[
            SensorReading(sensor_id="tool_wear_min", unit="min", value=216),
            SensorReading(sensor_id="torque_nm", unit="Nm", value=58),
            SensorReading(sensor_id="rotational_speed_rpm", unit="rpm", value=1450),
            SensorReading(sensor_id="air_temperature_k", unit="K", value=298.1),
            SensorReading(sensor_id="process_temperature_k", unit="K", value=308.6),
        ],
    )

    result = assess_risk(log)

    assert result.failure_type == "OSF"
    assert result.triggered_failure_types == ["OSF", "TWF"]


def test_uncertainty_text_cannot_fake_interaction_or_action_coverage() -> None:
    response = _grounded_response()
    response["diagnosis"]["causal_chain"] = [
        {
            "statement": "복합 오버스트레인이 OSF를 유발한다.",
            "evidence_ids": ["G4"],
        }
    ]
    response["claims"] = []
    response["diagnosis"]["root_cause"] = "복합 기계적 과부하"
    response["action_plan"] = []
    response["uncertainties"] = [
        "TWF 공구 마모가 절삭 저항을 통해 OSF에 기여할 수 있다.",
        "Feed Hold 후 안전 위치에서 스핀들을 정지하고 공구를 교체할 수 있다.",
    ]

    score = score_response("multi_path_kg_sop", response)

    assert score["checks"]["explains_twf_osf_interaction"] is False
    assert score["checks"]["feed_hold_safe_sequence"] is False
    assert score["checks"]["tool_replacement_and_reset"] is False
