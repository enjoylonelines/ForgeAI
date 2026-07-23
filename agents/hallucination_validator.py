from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from agents.base import BaseAgent, MaxRetriesExceededError
from agents.validation_strategy import get_strategy
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
            self._log("validator_empty_plan", correlation_id, equipment_id=action_plan.equipment_id)
            return ValidationResult(
                equipment_id=action_plan.equipment_id,
                validated_at=datetime.now(timezone.utc),
                overall_grounding_score=0.0,
                is_valid=False,
                step_validations=[],
                ungrounded_steps=[],
                recommendation="REJECT",
                explanation="Action plan has no steps — cannot verify grounding.",
                correlation_id=correlation_id,
            )

        # chunk_id → 청크 전체 임베딩 (ChromaDB 저장값)
        sop_embeddings: dict[str, list[float]] = {}
        # chunk_id → 문장 단위 임베딩 목록 (인용된 청크에 대해 추가 계산)
        sop_sentence_embeddings: dict[str, list[list[float]]] = {}

        chunk_text_map: dict[str, str] = {c.chunk_id: c.text for c in sop_context.chunks}

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

        # step.sop_reference가 있는 인용 청크에 대해 문장 단위 임베딩을 미리 계산
        cited_chunk_ids = {
            step.sop_reference
            for step in action_plan.steps
            if step.sop_reference and step.sop_reference in chunk_text_map
        }
        embeddings_client = get_embeddings()
        for cid in cited_chunk_ids:
            sentences = _split_sentences(chunk_text_map[cid])
            if sentences:
                vecs = await embeddings_client.aembed_documents(sentences)
                sop_sentence_embeddings[cid] = vecs

        strategy = get_strategy(
            nli_enabled=settings.nli_enabled,
            contradiction_threshold=settings.nli_contradiction_threshold,
        )
        strategy_name = "nli-hybrid" if settings.nli_enabled else "cosine"

        step_validations: list[StepValidation] = []
        for step in action_plan.steps:
            step_vec = await embeddings_client.aembed_query(step.action)
            cited = step.sop_reference if step.sop_reference in sop_sentence_embeddings else None

            scored = await strategy.score_step(
                action=step.action,
                step_vec=step_vec,
                sop_embeddings=sop_embeddings,
                sop_sentence_embeddings=sop_sentence_embeddings,
                sop_text_map=chunk_text_map,
                cited_chunk_id=cited,
            )

            step_validations.append(StepValidation(
                step_number=step.step_number,
                action=step.action,
                grounding_score=scored.grounding_score,
                best_matching_chunk_id=scored.best_chunk_id,
                is_grounded=scored.grounding_score >= threshold,
                nli_label=scored.nli_label,
                contradiction_detected=scored.contradiction_detected,
            ))

        scores = [sv.grounding_score for sv in step_validations]
        overall = round(sum(scores) / len(scores), 4) if scores else 0.0
        ungrounded = [sv.step_number for sv in step_validations if not sv.is_grounded]
        contradiction_count = sum(1 for sv in step_validations if sv.contradiction_detected)
        is_valid = overall >= threshold

        lf = get_langfuse()
        if lf:
            obs = lf.start_observation(
                name="grounding_validation",
                input={"step_count": len(action_plan.steps), "threshold": threshold, "strategy": strategy_name},
                output={"overall_grounding_score": overall, "ungrounded_steps": ungrounded, "contradiction_count": contradiction_count},
                metadata={"correlation_id": correlation_id},
            )
            obs.end()

        # contradiction 검출 시 즉시 REJECT (점수와 무관)
        if contradiction_count > 0:
            recommendation = "REJECT"
        elif overall >= settings.grounding_approve_threshold:
            recommendation = "APPROVE"
        elif overall >= settings.grounding_review_threshold:
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
            contradiction_count=contradiction_count,
            strategy=strategy_name,
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
            validation_strategy=strategy_name,
            contradiction_count=contradiction_count,
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


def _split_sentences(text: str, min_len: int = 15) -> list[str]:
    """마침표·느낌표·물음표 기준으로 문장 분할. 너무 짧은 조각은 제거."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if len(p.strip()) >= min_len]
