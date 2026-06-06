from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from models.action_plan import ActionPlan


ControlCommandType = Literal[
    "STOP_MACHINE",
    "LOCKOUT_TAGOUT",
    "SCHEDULE_INSPECTION",
    "NOTIFY_SUPERVISOR",
]


class ControlCommand(BaseModel):
    equipment_id: str
    command_type: ControlCommandType
    source_step_number: int | None = None
    priority: Literal["P1", "P2", "P3"] = "P2"
    reason: str
    dry_run: bool = True


class ControlExecutionResult(BaseModel):
    equipment_id: str
    command_type: ControlCommandType
    status: Literal["accepted", "rejected"]
    dry_run: bool
    adapter: str
    message: str
    correlation_id: str | None = None


class ControlPlanRequest(BaseModel):
    action_plan: ActionPlan
    dry_run: bool = Field(default=True, description="Live hardware writes are intentionally unsupported.")


class ControlPlanResult(BaseModel):
    correlation_id: str
    dry_run: bool
    command_count: int
    results: list[ControlExecutionResult]
    safety_note: str = "C++ adapter is wired in dry-run mode only; no PLC or actuator is modified."
