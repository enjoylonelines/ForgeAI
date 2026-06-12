from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class RiskFactor(BaseModel):
    sensor_id: str
    current_value: float
    safe_max: float | None = None
    safe_min: float | None = None
    utilization_pct: float | None = None
    description: str


class RiskAssessment(BaseModel):
    equipment_id: str
    assessed_at: datetime
    risk_level: Literal["SAFE", "WARNING", "CRITICAL"]
    failure_type: Literal["TWF", "HDF", "PWF", "OSF", "NONE"] | None = None
    triggered_failure_types: list[str] = []  # 동시에 참인 모든 고장 모드 (단일 라벨 한계 가시화)
    risk_factors: list[RiskFactor] = []
    summary: str
    recommended_action: str | None = None
    correlation_id: str | None = None
