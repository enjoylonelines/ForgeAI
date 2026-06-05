from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator


class SensorReading(BaseModel):
    sensor_id: str
    unit: str
    value: float


class EquipmentLog(BaseModel):
    equipment_id: str
    timestamp: datetime
    log_level: Literal["INFO", "WARN", "ERROR", "CRITICAL"] = "INFO"
    readings: list[SensorReading] = []
    message: str = ""
    tags: dict[str, str] = {}

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, v: object) -> object:
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v
