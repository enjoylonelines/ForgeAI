from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ActionStep(BaseModel):
    step_number: int
    action: str
    responsible_role: str
    priority: Literal["P1", "P2", "P3"]
    estimated_duration_minutes: int | None = None
    sop_reference: str | None = None


class ActionPlan(BaseModel):
    equipment_id: str
    generated_at: datetime
    steps: list[ActionStep] = []
    escalation_required: bool = False
    escalation_reason: str | None = None
    correlation_id: str | None = None
