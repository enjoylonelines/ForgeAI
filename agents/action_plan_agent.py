from __future__ import annotations

from datetime import datetime, timezone

from agents.base import BaseAgent, MaxRetriesExceededError, ParseOutputError
from models.action_plan import ActionPlan
from models.anomaly_report import AnomalyReport
from models.sop_context import SOPContext
from prompts import action_plan_v1 as prompt


class ActionPlanAgent(BaseAgent):
    def __init__(self, model: str | None = None) -> None:
        super().__init__(
            system_prompt=prompt.SYSTEM,
            model=model,
            prompt_name=prompt.NAME,
            prompt_version=prompt.VERSION,
        )

    async def run(
        self,
        anomaly_report: AnomalyReport,
        sop_context: SOPContext,
        correlation_id: str | None = None,
        previous_feedback: str | None = None,
        retry_attempt: int = 0,
    ) -> ActionPlan:
        self._log(
            "action_plan_agent_start",
            correlation_id,
            equipment_id=anomaly_report.equipment_id,
            retry_attempt=retry_attempt,
        )

        chunks_data = [c.model_dump() for c in sop_context.chunks]
        user_msg = prompt.format_user_message(
            anomaly_report.model_dump(mode="json"),
            chunks_data,
            previous_feedback=previous_feedback,
            retry_attempt=retry_attempt,
        )
        try:
            data = await self._invoke_chain(user_msg, correlation_id)
            data.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
            plan = ActionPlan.model_validate({**data, "correlation_id": correlation_id})
        except MaxRetriesExceededError:
            raise
        except Exception as exc:
            self._log("action_plan_agent_parse_error", correlation_id, error=str(exc))
            raise ParseOutputError(f"ActionPlanAgent parse failed: {exc}") from exc

        self._log(
            "action_plan_agent_complete",
            correlation_id,
            step_count=len(plan.steps),
            escalation_required=plan.escalation_required,
        )
        return plan
