from __future__ import annotations

from pydantic import BaseModel


class ToolCallRecord(BaseModel):
    tool_name: str
    args: dict
    output: dict


class DiagnosticResult(BaseModel):
    equipment_id: str
    risk_index: float | None = None
    risk_interpretation: str | None = None
    thresholds_checked: bool = False
    alert_dispatched: bool = False
    alert_id: str | None = None
    tool_calls: list[ToolCallRecord] = []
    summary: str = ""
