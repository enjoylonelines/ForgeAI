from __future__ import annotations

from datetime import datetime, timezone

from agents.base import BaseAgent, MaxRetriesExceededError, ParseOutputError
from models.equipment_log import EquipmentLog
from models.risk_assessment import RiskAssessment
from prompts import risk_assessment_v1 as prompt


class RiskAssessmentAgent(BaseAgent):
    def __init__(self, model: str | None = None) -> None:
        super().__init__(
            system_prompt=prompt.SYSTEM,
            model=model,
            prompt_name=prompt.NAME,
            prompt_version=prompt.VERSION,
        )

    async def run(
        self,
        log: EquipmentLog,
        correlation_id: str | None = None,
    ) -> RiskAssessment:
        self._log("risk_assessment_agent_start", correlation_id, equipment_id=log.equipment_id)

        user_msg = prompt.format_user_message(log.model_dump(mode="json"))
        try:
            data = await self._invoke_chain(user_msg, correlation_id)
            data.setdefault("assessed_at", datetime.now(timezone.utc).isoformat())
            assessment = RiskAssessment.model_validate({**data, "correlation_id": correlation_id})
        except MaxRetriesExceededError:
            raise
        except Exception as exc:
            self._log("risk_assessment_agent_parse_error", correlation_id, error=str(exc))
            raise ParseOutputError(f"RiskAssessmentAgent parse failed: {exc}") from exc

        self._log(
            "risk_assessment_agent_complete",
            correlation_id,
            risk_level=assessment.risk_level,
            risk_factor_count=len(assessment.risk_factors),
        )
        return assessment
