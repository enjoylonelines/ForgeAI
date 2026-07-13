from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

RoutingRoute = Literal["AUTO", "ESCALATE", "HUMAN_REVIEW"]


class RoutingInput(BaseModel):
    risk_level: str
    has_anomaly: bool
    plan_step_count: int
    retry_count: int
    max_retries: int
    recommendation: str | None = None
    verdict_conflict: bool = False


class RoutingDecision(BaseModel):
    route: RoutingRoute
    matched_rule: str
    reason: str
