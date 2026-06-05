from __future__ import annotations

from agents.base import BaseAgent, MaxRetriesExceededError, ParseOutputError
from models.user_query import ExtractedIntent
from prompts import intent_extraction_v1 as prompt


class IntentExtractionAgent(BaseAgent):
    def __init__(self, model: str | None = None) -> None:
        super().__init__(
            system_prompt=prompt.SYSTEM,
            model=model,
            prompt_name=prompt.NAME,
            prompt_version=prompt.VERSION,
        )

    async def run(
        self,
        query: str,
        equipment_id_override: str | None = None,
        correlation_id: str | None = None,
    ) -> ExtractedIntent:
        self._log("intent_extraction_start", correlation_id, query=query[:80])

        user_msg = prompt.format_user_message(query, equipment_id_override)
        try:
            data = await self._invoke_chain(user_msg, correlation_id)
        except MaxRetriesExceededError:
            raise
        except Exception as exc:
            raise ParseOutputError(f"IntentExtractionAgent parse failed: {exc}") from exc

        equipment_id = equipment_id_override or data.get("equipment_id")

        intent = ExtractedIntent(
            equipment_id=equipment_id,
            symptom_description=data.get("symptom_description", query),
            sensor_types=data.get("sensor_types", []),
            urgency=data.get("urgency", "medium"),
            failure_type_hints=data.get("failure_type_hints", []),
        )
        self._log("intent_extraction_complete", correlation_id, urgency=intent.urgency)
        return intent
