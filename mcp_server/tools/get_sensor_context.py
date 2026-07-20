"""get_sensor_context MCP tool — v1.0.0"""
from __future__ import annotations

import math

from pydantic import BaseModel, Field, field_validator

TOOL_VERSION = "1.0.0"

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


class GetSensorContextInput(BaseModel):
    equipment_type: str = Field(
        ..., description="설비 등급 — 'H' (High), 'M' (Medium), 'L' (Low)"
    )
    tool_wear_min: float = Field(..., ge=0.0, le=500.0, description="공구 마모 (분)")
    torque_nm: float = Field(..., ge=0.0, le=200.0, description="토크 (N·m)")
    rotational_speed_rpm: float = Field(
        ..., ge=0.0, le=5000.0, description="회전 속도 (RPM)"
    )

    @field_validator("equipment_type", mode="before")
    @classmethod
    def normalise_type(cls, v: str) -> str:
        upper = v.strip().upper()
        if upper not in _THRESHOLDS:
            raise ValueError(f"equipment_type must be H, M, or L, got '{v}'")
        return upper


def run_get_sensor_context(
    equipment_type: str,
    tool_wear_min: float,
    torque_nm: float,
    rotational_speed_rpm: float,
) -> dict:
    thresholds = _THRESHOLDS[equipment_type]

    def _status(key: str, value: float) -> str:
        lo, hi = thresholds[key]
        return "NORMAL" if lo <= value <= hi else "ABNORMAL"

    # 리스크 인덱스 (tools/sensor_tools.py 공식 동일)
    wear_ratio = min(tool_wear_min / 200.0, 1.0)
    power_w = torque_nm * rotational_speed_rpm * (2.0 * math.pi / 60.0)
    overstrain_ratio = min(max(power_w - 7_000.0, 0.0) / 3_000.0, 1.0)
    risk_index = round(wear_ratio * 60.0 + overstrain_ratio * 40.0, 1)

    sensor_snapshot = {
        "tool_wear_min": {"value": tool_wear_min, "status": _status("tool_wear_min", tool_wear_min)},
        "torque_nm": {"value": torque_nm, "status": _status("torque_nm", torque_nm)},
        "rotational_speed_rpm": {
            "value": rotational_speed_rpm,
            "status": _status("rotational_speed_rpm", rotational_speed_rpm),
        },
    }

    return {
        "tool": "get_sensor_context",
        "version": TOOL_VERSION,
        "equipment_type": equipment_type,
        "thresholds": {k: {"min": v[0], "max": v[1]} for k, v in thresholds.items()},
        "sensor_snapshot": sensor_snapshot,
        "risk_index": risk_index,
        "risk_level": "HIGH" if risk_index > 60 else "MEDIUM" if risk_index > 30 else "LOW",
        "power_w": round(power_w, 1),
    }
