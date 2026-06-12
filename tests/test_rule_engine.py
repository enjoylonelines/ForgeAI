from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.rule_engine import (
    _CRITICAL_UTILIZATION,
    _SENSOR_RANGES,
    _TOOL_WEAR_WARNING_THRESHOLD,
    _WARNING_UTILIZATION,
    assess_risk,
    classify_failure_type,
)
from models.equipment_log import EquipmentLog, SensorReading


def _make_log(*readings: tuple[str, float]) -> EquipmentLog:
    return EquipmentLog(
        equipment_id="TEST-001",
        timestamp=datetime(2026, 6, 8, 0, 0, 0, tzinfo=timezone.utc),
        readings=[
            SensorReading(sensor_id=sid, unit="", value=val)
            for sid, val in readings
        ],
    )


# ── SAFE ──────────────────────────────────────────────────────────────────────

def test_safe_all_mid_range():
    log = _make_log(
        ("air_temperature_k", 300.0),
        ("process_temperature_k", 309.0),
        ("rotational_speed_rpm", 2000.0),
        ("torque_nm", 40.0),
        ("tool_wear_min", 100.0),
    )
    result = assess_risk(log)
    assert result.risk_level == "SAFE"
    assert result.risk_factors == []
    assert result.recommended_action is None


def test_safe_tool_wear_exactly_at_threshold():
    # 200 min is the boundary — not exceeding, so SAFE
    log = _make_log(("tool_wear_min", 200.0))
    result = assess_risk(log)
    assert result.risk_level == "SAFE"


# ── WARNING ───────────────────────────────────────────────────────────────────

def test_warning_tool_wear_explicit_threshold():
    # 201 > 200 → WARNING by explicit threshold (utilization = 80.4%, below 85%)
    log = _make_log(("tool_wear_min", 201.0))
    result = assess_risk(log)
    assert result.risk_level == "WARNING"
    assert len(result.risk_factors) == 1
    assert result.risk_factors[0].sensor_id == "tool_wear_min"


def test_warning_tool_wear_high_utilization():
    # 216 min → utilization = 86.4% → WARNING by utilization threshold
    log = _make_log(("tool_wear_min", 216.0))
    result = assess_risk(log)
    assert result.risk_level == "WARNING"
    assert result.risk_factors[0].utilization_pct == pytest.approx(86.4, abs=0.2)


def test_warning_torque_approaching_max():
    # torque at 88% utilization: 3.8 + 0.88*(76.6-3.8) = 3.8 + 64.1 = 67.9
    value = 3.8 + 0.88 * (76.6 - 3.8)
    log = _make_log(("torque_nm", round(value, 1)))
    result = assess_risk(log)
    assert result.risk_level == "WARNING"


def test_warning_single_sensor_does_not_escalate():
    log = _make_log(("tool_wear_min", 216.0))
    result = assess_risk(log)
    assert result.risk_level == "WARNING"  # single factor stays WARNING


# ── CRITICAL ─────────────────────────────────────────────────────────────────

def test_critical_sensor_above_95_pct():
    # torque at 96% utilization: 3.8 + 0.96*(76.6-3.8) = 73.8
    value = 3.8 + 0.96 * (76.6 - 3.8)
    log = _make_log(("torque_nm", round(value, 1)))
    result = assess_risk(log)
    assert result.risk_level == "CRITICAL"
    assert any(f.sensor_id == "torque_nm" for f in result.risk_factors)


def test_critical_two_simultaneous_warnings():
    # Two WARNING sensors → escalate to CRITICAL
    tool_wear_warning = 216.0        # 86.4% utilization
    torque_warning = 3.8 + 0.88 * (76.6 - 3.8)  # 88% utilization
    log = _make_log(
        ("tool_wear_min", tool_wear_warning),
        ("torque_nm", round(torque_warning, 1)),
    )
    result = assess_risk(log)
    assert result.risk_level == "CRITICAL"
    assert len(result.risk_factors) == 2


# ── model shape ───────────────────────────────────────────────────────────────

def test_output_model_shape():
    log = _make_log(("tool_wear_min", 216.0))
    result = assess_risk(log, correlation_id="cid-123")
    assert result.equipment_id == "TEST-001"
    assert result.correlation_id == "cid-123"
    assert result.assessed_at is not None
    assert result.summary != ""

    factor = result.risk_factors[0]
    assert factor.safe_max == _SENSOR_RANGES["tool_wear_min"]["max"]
    assert factor.safe_min == _SENSOR_RANGES["tool_wear_min"]["min"]
    assert factor.current_value == 216.0


def test_unknown_sensor_ignored():
    log = _make_log(("unknown_sensor_xyz", 9999.0))
    result = assess_risk(log)
    assert result.risk_level == "SAFE"
    assert result.risk_factors == []


def test_correlation_id_none_allowed():
    log = _make_log(("air_temperature_k", 300.0))
    result = assess_risk(log)
    assert result.correlation_id is None


# ── failure_type classification ────────────────────────────────────────────────

def test_classify_twf():
    log = _make_log(("tool_wear_min", 201.0))
    assert classify_failure_type(log) == "TWF"


def test_classify_hdf():
    # process_temp - air_temp = 7.0 < 8.6, rpm = 1300 < 1380
    log = _make_log(
        ("air_temperature_k", 300.0),
        ("process_temperature_k", 307.0),
        ("rotational_speed_rpm", 1300.0),
    )
    assert classify_failure_type(log) == "HDF"


def test_classify_pwf_underpowered():
    # power = 10 Nm × (500 rpm × 2π/60) = 10 × 52.36 = 523.6 W < 3500 W
    log = _make_log(
        ("torque_nm", 10.0),
        ("rotational_speed_rpm", 500.0),
    )
    assert classify_failure_type(log) == "PWF"


def test_classify_pwf_overpowered():
    # power = 70 Nm × (1500 rpm × 2π/60) = 70 × 157.08 = 10996 W > 9000 W
    log = _make_log(
        ("torque_nm", 70.0),
        ("rotational_speed_rpm", 1500.0),
    )
    assert classify_failure_type(log) == "PWF"


def test_classify_osf():
    # tool_wear=150, torque=80 → 150×80=12000 > 11000; no TWF (150≤200), no HDF/PWF sensors
    log = _make_log(
        ("tool_wear_min", 150.0),
        ("torque_nm", 80.0),
    )
    assert classify_failure_type(log) == "OSF"


def test_classify_none():
    log = _make_log(
        ("air_temperature_k", 300.0),
        ("process_temperature_k", 309.0),
        ("rotational_speed_rpm", 2000.0),
        ("torque_nm", 40.0),
        ("tool_wear_min", 100.0),
    )
    assert classify_failure_type(log) == "NONE"


def test_classify_osf_priority_over_twf():
    # tool_wear=210 (>200 → TWF), torque=80 → 210×80=16800 (also OSF)
    # 우선순위: OSF(물리 부상 위험) > TWF(점진적 마모) — OSF wins
    log = _make_log(
        ("tool_wear_min", 210.0),
        ("torque_nm", 80.0),
    )
    assert classify_failure_type(log) == "OSF"


def test_assess_risk_attaches_failure_type():
    # WARNING → failure_type should be classified (not NONE)
    log = _make_log(("tool_wear_min", 201.0))
    result = assess_risk(log)
    assert result.failure_type == "TWF"


def test_assess_risk_safe_returns_none_failure_type():
    log = _make_log(("tool_wear_min", 100.0))
    result = assess_risk(log)
    assert result.risk_level == "SAFE"
    assert result.failure_type == "NONE"
