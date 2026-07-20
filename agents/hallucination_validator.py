from __future__ import annotations

import math
from datetime import datetime, timezone

from agents.base import BaseAgent, MaxRetriesExceededError
from core.config import get_settings
from core.langchain_client import get_embeddings
from core.langfuse_client import get_langfuse
from core.logging import get_logger
from models.action_plan import ActionPlan
from models.sop_context import SOPContext
from models.validation_result import StepValidation, ValidationResult
from prompts import hallucination_v1 as prompt
from rag.chroma_client import get_sop_collection

logger = get_logger(__name__)


class HallucinationValidatorAgent(BaseAgent):
    def __init__(self, model: str | None = None) -> None:
        super().__init__(
            system_prompt=prompt.SYSTEM,
            model=model,
            prompt_name=prompt.NAME,
            prompt_version=prompt.VERSION,
        )

    async def run(
        self,
        action_plan: ActionPlan,
        sop_context: SOPContext,
        correlation_id: str | None = None,
    ) -> ValidationResult:
        self._log("validator_start", correlation_id, equipment_id=action_plan.equipment_id)
        settings = get_settings()
        threshold = settings.grounding_score_threshold

        if not action_plan.steps:
            return ValidationResult(
                equipment_id=action_plan.equipment_id,
                validated_at=datetime.now(timezone.utc),
                overall_grounding_score=1.0,
                is_valid=True,
                step_validations=[],
                ungrounded_steps=[],
                recommendation="APPROVE",
                correlation_id=correlation_id,
            )

        sop_embeddings: dict[str, list[float]] = {}
        if sop_context.chunks:
            chunk_ids = [c.chunk_id for c in sop_context.chunks]
            try:
                result = get_sop_collection().get(ids=chunk_ids, include=["embeddings"])
                for cid, emb in zip(result["ids"], result["embeddings"]):
                    sop_embeddings[cid] = emb
            except Exception as exc:
                logger.warning({
                    "event": "validator_embedding_fetch_error",
                    "correlation_id": correlation_id,
                    "error": str(exc),
                })

        embeddings_client = get_embeddings()
        step_validations: list[StepValidation] = []
        for step in action_plan.steps:
            step_vec = await embeddings_client.aembed_query(step.action)

            best_score = 0.0
            best_chunk_id: str | None = None
            for chunk_id, sop_vec in sop_embeddings.items():
                score = _cosine_similarity(step_vec, sop_vec)
                if score > best_score:
                    best_score = score
                    best_chunk_id = chunk_id

            step_validations.append(StepValidation(
                step_number=step.step_number,
                action=step.action,
                grounding_score=round(best_score, 4),
                best_matching_chunk_id=best_chunk_id,
                is_grounded=best_score >= threshold,
            ))

        scores = [sv.grounding_score for sv in step_validations]
        overall = round(sum(scores) / len(scores), 4) if scores else 0.0
        ungrounded = [sv.step_number for sv in step_validations if not sv.is_grounded]
        is_valid = overall >= threshold

        lf = get_langfuse()
        if lf:
            obs = lf.start_observation(
                name="cosine_grounding",
                input={"step_count": len(action_plan.steps), "threshold": threshold},
                output={"overall_grounding_score": overall, "ungrounded_steps": ungrounded},
                metadata={"correlation_id": correlation_id},
            )
            obs.end()

        if overall >= 0.85:
            recommendation = "APPROVE"
        elif overall >= 0.60:
            recommendation = "REVIEW"
        else:
            recommendation = "REJECT"

        explanation: str | None = None
        if not is_valid and ungrounded:
            explanation = await self._generate_explanation(
                action_plan, ungrounded, overall, correlation_id
            )

        self._log(
            "validator_complete",
            correlation_id,
            overall_grounding_score=overall,
            recommendation=recommendation,
            ungrounded_count=len(ungrounded),
        )
        return ValidationResult(
            equipment_id=action_plan.equipment_id,
            validated_at=datetime.now(timezone.utc),
            overall_grounding_score=overall,
            is_valid=is_valid,
            step_validations=step_validations,
            ungrounded_steps=ungrounded,
            recommendation=recommendation,
            explanation=explanation,
            correlation_id=correlation_id,
        )

    async def _generate_explanation(
        self,
        action_plan: ActionPlan,
        ungrounded_steps: list[int],
        overall_score: float,
        correlation_id: str | None,
    ) -> str | None:
        user_msg = prompt.format_user_message(
            action_plan.model_dump(mode="json"),
            ungrounded_steps,
            overall_score,
        )
        try:
            data = await self._invoke_chain(user_msg, correlation_id)
            return data.get("explanation")
        except (MaxRetriesExceededError, Exception) as exc:
            logger.warning({"event": "validator_explanation_failed", "error": str(exc)})
            return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
