from __future__ import annotations

import math
from datetime import datetime, timezone

from models.equipment_log import EquipmentLog
from models.risk_assessment import RiskAssessment, RiskFactor

_SENSOR_RANGES: dict[str, dict[str, float]] = {
    "air_temperature_k":     {"min": 295.0, "max": 304.0},
    "process_temperature_k": {"min": 305.0, "max": 313.0},
    "rotational_speed_rpm":  {"min": 1168.0, "max": 2886.0},
    "torque_nm":             {"min": 3.8,   "max": 76.6},
    "tool_wear_min":         {"min": 0.0,   "max": 250.0},
}

# Explicit WARNING threshold separate from utilization (from AI4I 2020 prompt spec)
_TOOL_WEAR_WARNING_THRESHOLD = 200.0

_WARNING_UTILIZATION = 85.0   # within 15% of upper boundary
_CRITICAL_UTILIZATION = 95.0  # within 5% of upper boundary

# AI4I 2020 failure type thresholds
_TWF_TOOL_WEAR_MIN = 200.0        # tool_wear_min > 200 → TWF
_HDF_TEMP_DIFF_MIN = 8.6          # process_temp - air_temp < 8.6 K → HDF condition
_HDF_RPM_MAX = 1380.0             # rotational_speed_rpm < 1380 → HDF condition
_PWF_POWER_MIN_W = 3500.0         # power < 3500 W → PWF
_PWF_POWER_MAX_W = 9000.0         # power > 9000 W → PWF
_OSF_STRAIN_THRESHOLD = 11000.0   # tool_wear_min × torque_nm > 11000 → OSF (L-type conservative)


def classify_failure_type(log: EquipmentLog) -> str:
    """Deterministically classify failure type from sensor readings.

    Priority: TWF > HDF > PWF > OSF > NONE.
    Returns one of: "TWF", "HDF", "PWF", "OSF", "NONE".
    """
    readings = {r.sensor_id: r.value for r in log.readings}

    tool_wear = readings.get("tool_wear_min")
    air_temp = readings.get("air_temperature_k")
    process_temp = readings.get("process_temperature_k")
    rpm = readings.get("rotational_speed_rpm")
    torque = readings.get("torque_nm")

    if tool_wear is not None and tool_wear > _TWF_TOOL_WEAR_MIN:
        return "TWF"

    if air_temp is not None and process_temp is not None and rpm is not None:
        if (process_temp - air_temp) < _HDF_TEMP_DIFF_MIN and rpm < _HDF_RPM_MAX:
            return "HDF"

    if torque is not None and rpm is not None:
        power_w = torque * (rpm * 2 * math.pi / 60)
        if power_w < _PWF_POWER_MIN_W or power_w > _PWF_POWER_MAX_W:
            return "PWF"

    if tool_wear is not None and torque is not None:
        if tool_wear * torque > _OSF_STRAIN_THRESHOLD:
            return "OSF"

    return "NONE"


def _classify(sensor_id: str, value: float, util_pct: float) -> str | None:
    if util_pct >= _CRITICAL_UTILIZATION:
        return "CRITICAL"
    if util_pct >= _WARNING_UTILIZATION:
        return "WARNING"
    if sensor_id == "tool_wear_min" and value > _TOOL_WEAR_WARNING_THRESHOLD:
        return "WARNING"
    return None


def assess_risk(log: EquipmentLog, correlation_id: str | None = None) -> RiskAssessment:
    critical_factors: list[RiskFactor] = []
    warning_factors: list[RiskFactor] = []

    for reading in log.readings:
        rng = _SENSOR_RANGES.get(reading.sensor_id)
        if rng is None:
            continue

        lo, hi = rng["min"], rng["max"]
        util_pct = round((reading.value - lo) / (hi - lo) * 100.0, 1)
        severity = _classify(reading.sensor_id, reading.value, util_pct)
        if severity is None:
            continue

        if severity == "CRITICAL":
            desc = f"{reading.sensor_id} at {util_pct}% of safe range — near upper boundary"
        elif util_pct >= _WARNING_UTILIZATION:
            desc = f"{reading.sensor_id} at {util_pct}% of safe range — approaching upper boundary"
        else:
            desc = (
                f"{reading.sensor_id} {reading.value} min — exceeds "
                f"{_TOOL_WEAR_WARNING_THRESHOLD:.0f} min replacement threshold"
            )

        factor = RiskFactor(
            sensor_id=reading.sensor_id,
            current_value=reading.value,
            safe_max=hi,
            safe_min=lo,
            utilization_pct=util_pct,
            description=desc,
        )

        if severity == "CRITICAL":
            critical_factors.append(factor)
        else:
            warning_factors.append(factor)

    # Multiple simultaneous WARNINGs escalate to CRITICAL (per spec)
    if critical_factors or len(warning_factors) >= 2:
        risk_level = "CRITICAL"
        all_factors = critical_factors + warning_factors
    elif warning_factors:
        risk_level = "WARNING"
        all_factors = warning_factors
    else:
        risk_level = "SAFE"
        all_factors = []

    failure_type = classify_failure_type(log) if risk_level != "SAFE" else "NONE"

    return RiskAssessment(
        equipment_id=log.equipment_id,
        assessed_at=datetime.now(timezone.utc),
        risk_level=risk_level,
        failure_type=failure_type,
        risk_factors=all_factors,
        summary=_make_summary(risk_level, all_factors),
        recommended_action=_make_action(risk_level),
        correlation_id=correlation_id,
    )


def _make_summary(risk_level: str, factors: list[RiskFactor]) -> str:
    if risk_level == "SAFE":
        return "All sensors within normal operating range."
    sensor_names = ", ".join(f.sensor_id for f in factors)
    if risk_level == "CRITICAL":
        return (
            f"Critical risk detected: {sensor_names} at or near operating boundary. "
            "Immediate action required."
        )
    return (
        f"Risk warning: {sensor_names} approaching operating limits. "
        "Preventive inspection recommended within the shift."
    )


def _make_action(risk_level: str) -> str | None:
    if risk_level == "SAFE":
        return None
    if risk_level == "CRITICAL":
        return "Halt machine immediately and perform emergency inspection."
    return "Schedule preventive inspection within the current shift."
