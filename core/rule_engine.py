from __future__ import annotations

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

    return RiskAssessment(
        equipment_id=log.equipment_id,
        assessed_at=datetime.now(timezone.utc),
        risk_level=risk_level,
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
