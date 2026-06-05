from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class StepValidation(BaseModel):
    step_number: int
    action: str
    grounding_score: float
    best_matching_chunk_id: str | None = None
    is_grounded: bool


class ValidationResult(BaseModel):
    equipment_id: str
    validated_at: datetime
    overall_grounding_score: float
    is_valid: bool
    step_validations: list[StepValidation] = []
    ungrounded_steps: list[int] = []
    recommendation: Literal["APPROVE", "REVIEW", "REJECT"]
    explanation: str | None = None
    correlation_id: str | None = None
