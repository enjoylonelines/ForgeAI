from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class AnomalyDetail(BaseModel):
    sensor_id: str
    observed_value: float
    expected_range: tuple[float, float] | None = None
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    description: str


class AnomalyReport(BaseModel):
    equipment_id: str
    timestamp: datetime
    has_anomaly: bool
    anomalies: list[AnomalyDetail] = []
    summary: str
    raw_log_snippet: str
    tags: dict[str, str] = {}
    correlation_id: str | None = None
