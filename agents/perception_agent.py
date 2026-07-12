from __future__ import annotations

from agents.base import BaseAgent, MaxRetriesExceededError, ParseOutputError
from models.anomaly_report import AnomalyReport
from models.equipment_log import EquipmentLog
from prompts import perception_v1 as prompt


class PerceptionAgent(BaseAgent):
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
    ) -> AnomalyReport:
        self._log("perception_agent_start", correlation_id, equipment_id=log.equipment_id)

        observable = {
            "equipment_id": log.equipment_id,
            "timestamp": log.timestamp.isoformat(),
            "log_level": log.log_level,
            "readings": [r.model_dump() for r in log.readings],
        }
        user_msg = prompt.format_user_message(observable)
        try:
            data = await self._invoke_chain(user_msg, correlation_id)
            report = AnomalyReport.model_validate({**data, "correlation_id": correlation_id, "tags": log.tags})
        except MaxRetriesExceededError:
            raise
        except Exception as exc:
            self._log("perception_agent_parse_error", correlation_id, error=str(exc))
            raise ParseOutputError(f"PerceptionAgent parse failed: {exc}") from exc

        self._log(
            "perception_agent_complete",
            correlation_id,
            has_anomaly=report.has_anomaly,
            anomaly_count=len(report.anomalies),
        )
        return report
