from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.rule_engine import (
    _CRITICAL_UTILIZATION,
    _SENSOR_RANGES,
    _TOOL_WEAR_WARNING_THRESHOLD,
    _WARNING_UTILIZATION,
    assess_risk,
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
