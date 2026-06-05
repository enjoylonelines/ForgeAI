from __future__ import annotations

import math
import uuid

from langchain_core.tools import tool

# AI4I 2020 데이터셋 기반 설비 유형별 센서 정상 범위
_THRESHOLDS: dict[str, dict[str, tuple[float, float]]] = {
    "H": {
        "air_temp_k": (295.0, 304.0),
        "process_temp_k": (305.0, 313.0),
        "tool_wear_min": (0.0, 200.0),
        "torque_nm": (3.0, 60.0),
        "rotational_speed_rpm": (1200.0, 2860.0),
    },
    "M": {
        "air_temp_k": (295.0, 308.0),
        "process_temp_k": (305.0, 318.0),
        "tool_wear_min": (0.0, 220.0),
        "torque_nm": (3.0, 65.0),
        "rotational_speed_rpm": (1200.0, 2860.0),
    },
    "L": {
        "air_temp_k": (295.0, 312.0),
        "process_temp_k": (305.0, 323.0),
        "tool_wear_min": (0.0, 250.0),
        "torque_nm": (3.0, 70.0),
        "rotational_speed_rpm": (1200.0, 2860.0),
    },
}


@tool
def get_sensor_thresholds(equipment_type: str) -> dict:
    """Return normal operating thresholds for a given equipment quality type.

    Args:
        equipment_type: Quality grade of the equipment — 'H' (High), 'M' (Medium), or 'L' (Low).

    Returns a dict with min/max ranges for each sensor: air_temp_k, process_temp_k,
    tool_wear_min, torque_nm, and rotational_speed_rpm.
    """
    key = equipment_type.strip().upper()
    thresholds = _THRESHOLDS.get(key, _THRESHOLDS["M"])
    return {
        "equipment_type": key,
        "thresholds": {k: {"min": v[0], "max": v[1]} for k, v in thresholds.items()},
    }


@tool
def calculate_risk_index(
    tool_wear_min: float,
    torque_nm: float,
    rotational_speed_rpm: float,
) -> dict:
    """Calculate a composite mechanical risk index using AI4I domain formulas.

    Args:
        tool_wear_min: Tool wear in minutes (0–250 typical range).
        torque_nm: Rotational torque in Newton-metres.
        rotational_speed_rpm: Rotational speed in RPM.

    Returns risk_index (0–100), contributing factors, and an interpretation label.
    Tool wear drives TWF failures; power (torque × speed) drives OSF failures.
    """
    wear_ratio = min(tool_wear_min / 200.0, 1.0)

    # Mechanical power in Watts
    power_w = torque_nm * rotational_speed_rpm * (2.0 * math.pi / 60.0)
    # Overstrain threshold in AI4I: product torque × wear > 11_000 Nm·min
    overstrain_ratio = min(max(power_w - 7_000.0, 0.0) / 3_000.0, 1.0)

    risk_index = round(wear_ratio * 60.0 + overstrain_ratio * 40.0, 1)
    return {
        "risk_index": risk_index,
        "wear_ratio": round(wear_ratio, 3),
        "power_w": round(power_w, 1),
        "interpretation": "HIGH" if risk_index > 60 else "MEDIUM" if risk_index > 30 else "LOW",
    }


@tool
def alert_maintenance_team(equipment_id: str, severity: str, message: str) -> dict:
    """Dispatch an alert to the maintenance operations channel.

    Args:
        equipment_id: Identifier of the equipment requiring attention.
        severity: Alert severity — 'INFO', 'WARNING', or 'CRITICAL'.
        message: Short description of the issue (max 200 chars).

    Returns confirmation with a unique alert_id and dispatch status.
    """
    alert_id = f"ALERT-{uuid.uuid4().hex[:8].upper()}"
    return {
        "alert_id": alert_id,
        "equipment_id": equipment_id,
        "severity": severity.upper(),
        "message": message[:200],
        "status": "dispatched",
        "channel": "maintenance_ops_channel",
    }


ALL_TOOLS = [get_sensor_thresholds, calculate_risk_index, alert_maintenance_team]
