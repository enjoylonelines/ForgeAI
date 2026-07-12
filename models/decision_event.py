from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class DecisionEvent(BaseModel):
    correlation_id: str
    stage: str
    signals: dict
    decision: str
    reason: str
    policy_version: str = "pipeline-v1"
    duration_ms: float
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
