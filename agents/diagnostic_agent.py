from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from core.langchain_client import get_chat_llm
from core.langfuse_client import get_current_trace
from core.logging import get_logger
from models.anomaly_report import AnomalyReport
from models.diagnostic_result import DiagnosticResult, ToolCallRecord
from tools.sensor_tools import ALL_TOOLS, alert_maintenance_team, calculate_risk_index, get_sensor_thresholds

logger = get_logger(__name__)

_SYSTEM = """\
You are a Diagnostic Agent for an industrial equipment monitoring system.

Given an anomaly report with sensor readings, your job is to:
1. Call get_sensor_thresholds with the equipment type to verify which readings are out of range.
2. Call calculate_risk_index using tool_wear_min, torque_nm, and rotational_speed_rpm values.
3. If risk_index > 60 OR any anomaly is labelled CRITICAL, call alert_maintenance_team.

After using the tools, write a concise diagnostic summary (2-3 sentences) explaining:
- Which sensors are out of normal range
- The calculated risk index and its interpretation
- Whether an alert was dispatched

Always call the tools in order: thresholds → risk_index → (optional) alert.
"""

_TOOL_REGISTRY: dict[str, Any] = {
    "get_sensor_thresholds": get_sensor_thresholds,
    "calculate_risk_index": calculate_risk_index,
    "alert_maintenance_team": alert_maintenance_team,
}


def _extract_sensor_value(readings: list[dict], sensor_id: str) -> float | None:
    for r in readings:
        if r.get("sensor_id", "").lower() == sensor_id.lower():
            return float(r["value"])
    return None


class DiagnosticAgent:
    MAX_ITERATIONS = 5

    def __init__(self, model: str | None = None) -> None:
        llm = get_chat_llm(model)
        self._llm = llm.bind_tools(ALL_TOOLS)

    async def run(
        self,
        anomaly_report: AnomalyReport,
        correlation_id: str | None = None,
    ) -> DiagnosticResult:
        logger.info({
            "event": "diagnostic_agent_start",
            "correlation_id": correlation_id,
            "equipment_id": anomaly_report.equipment_id,
        })

        readings = [r.model_dump() for r in anomaly_report.anomalies] if anomaly_report.anomalies else []
        equipment_type = anomaly_report.tags.get("type", "M")

        user_content = (
            f"Equipment ID: {anomaly_report.equipment_id}\n"
            f"Equipment type: {equipment_type}\n"
            f"Summary: {anomaly_report.summary}\n"
            f"Anomalies detected: {json.dumps(readings, default=str)}\n"
            f"Raw sensor readings from log: {json.dumps([r.model_dump() for r in (anomaly_report.anomalies or [])], default=str)}\n\n"
            "Please diagnose this equipment using the available tools."
        )

        messages: list = [SystemMessage(content=_SYSTEM), HumanMessage(content=user_content)]

        tool_call_records: list[ToolCallRecord] = []
        risk_index: float | None = None
        risk_interpretation: str | None = None
        thresholds_checked = False
        alert_dispatched = False
        alert_id: str | None = None
        final_summary = ""

        lf_trace = get_current_trace()
        generation = None
        if lf_trace:
            generation = lf_trace.generation(
                name="DiagnosticAgent",
                model=None,
                input=user_content,
                metadata={"correlation_id": correlation_id, "prompt_version": "diagnostic_v1"},
            )

        for iteration in range(self.MAX_ITERATIONS):
            response: AIMessage = await self._llm.ainvoke(messages)
            messages.append(response)

            if not response.tool_calls:
                final_summary = response.content if isinstance(response.content, str) else ""
                break

            for tc in response.tool_calls:
                tool_name: str = tc["name"]
                tool_args: dict = tc["args"]
                tool_fn = _TOOL_REGISTRY.get(tool_name)

                if tool_fn is None:
                    tool_output = {"error": f"Unknown tool: {tool_name}"}
                else:
                    try:
                        raw = tool_fn.invoke(tool_args)
                        tool_output = raw if isinstance(raw, dict) else {"result": raw}
                    except Exception as exc:
                        tool_output = {"error": str(exc)}

                tool_call_records.append(ToolCallRecord(
                    tool_name=tool_name,
                    args=tool_args,
                    output=tool_output,
                ))

                if tool_name == "get_sensor_thresholds" and "error" not in tool_output:
                    thresholds_checked = True
                elif tool_name == "calculate_risk_index" and "error" not in tool_output:
                    risk_index = tool_output.get("risk_index")
                    risk_interpretation = tool_output.get("interpretation")
                elif tool_name == "alert_maintenance_team" and "error" not in tool_output:
                    alert_dispatched = True
                    alert_id = tool_output.get("alert_id")

                messages.append(ToolMessage(
                    content=json.dumps(tool_output),
                    tool_call_id=tc["id"],
                ))

        if generation:
            generation.end(output={"summary": final_summary, "tool_calls": len(tool_call_records)})

        result = DiagnosticResult(
            equipment_id=anomaly_report.equipment_id,
            risk_index=risk_index,
            risk_interpretation=risk_interpretation,
            thresholds_checked=thresholds_checked,
            alert_dispatched=alert_dispatched,
            alert_id=alert_id,
            tool_calls=tool_call_records,
            summary=final_summary,
        )

        logger.info({
            "event": "diagnostic_agent_complete",
            "correlation_id": correlation_id,
            "equipment_id": anomaly_report.equipment_id,
            "risk_index": risk_index,
            "tool_call_count": len(tool_call_records),
            "alert_dispatched": alert_dispatched,
        })
        return result
