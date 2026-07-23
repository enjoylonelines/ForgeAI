"""검증 전략 인터페이스 — 코사인 유사도 vs NLI hybrid.

전략 선택:
  NLI_ENABLED=false (기본) → CosineStrategy  (기존 동작 유지)
  NLI_ENABLED=true         → NLIHybridStrategy (cosine + contradiction 검출)
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

from core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class StepScore:
    grounding_score: float          # 코사인 유사도 기반 근거 점수
    best_chunk_id: str | None       # 가장 유사한 청크 ID
    nli_label: str | None = None    # "entailment" | "neutral" | "contradiction" | None
    contradiction_detected: bool = False


class ValidationStrategy(ABC):
    @abstractmethod
    async def score_step(
        self,
        action: str,
        step_vec: list[float],
        sop_embeddings: dict[str, list[float]],
        sop_sentence_embeddings: dict[str, list[list[float]]],
        sop_text_map: dict[str, str],
        cited_chunk_id: str | None,
    ) -> StepScore:
        """단일 조치 단계를 SOP 청크들과 비교해 StepScore를 반환한다."""


class CosineStrategy(ValidationStrategy):
    """기존 코사인 유사도 전략 — 변경 없음."""

    async def score_step(
        self,
        action: str,
        step_vec: list[float],
        sop_embeddings: dict[str, list[float]],
        sop_sentence_embeddings: dict[str, list[list[float]]],
        sop_text_map: dict[str, str],
        cited_chunk_id: str | None,
    ) -> StepScore:
        best_score = 0.0
        best_chunk_id: str | None = None

        for chunk_id, sop_vec in sop_embeddings.items():
            score = _cosine_similarity(step_vec, sop_vec)
            if score > best_score:
                best_score = score
                best_chunk_id = chunk_id

        if cited_chunk_id and cited_chunk_id in sop_sentence_embeddings:
            for sent_vec in sop_sentence_embeddings[cited_chunk_id]:
                score = _cosine_similarity(step_vec, sent_vec)
                if score > best_score:
                    best_score = score
                    best_chunk_id = cited_chunk_id

        return StepScore(
            grounding_score=round(best_score, 4),
            best_chunk_id=best_chunk_id,
        )


class NLIHybridStrategy(ValidationStrategy):
    """코사인 유사도 + NLI contradiction 검출 하이브리드 전략.

    판정 우선순위:
      1. contradiction_score >= NLI_CONTRADICTION_THRESHOLD → REJECT 신호 (grounding_score=0.0)
      2. NLI label == "neutral" → grounding_score를 0.5로 클램프 (REVIEW 유도)
      3. 나머지는 코사인 점수 그대로
    """

    def __init__(self, contradiction_threshold: float = 0.5) -> None:
        self._threshold = contradiction_threshold

    async def score_step(
        self,
        action: str,
        step_vec: list[float],
        sop_embeddings: dict[str, list[float]],
        sop_sentence_embeddings: dict[str, list[list[float]]],
        sop_text_map: dict[str, str],
        cited_chunk_id: str | None,
    ) -> StepScore:
        from core.nli_validator import NLIValidator

        # 1) 코사인 유사도로 최적 청크 선정
        best_cosine = 0.0
        best_chunk_id: str | None = None
        for chunk_id, sop_vec in sop_embeddings.items():
            score = _cosine_similarity(step_vec, sop_vec)
            if score > best_cosine:
                best_cosine = score
                best_chunk_id = chunk_id

        if cited_chunk_id and cited_chunk_id in sop_sentence_embeddings:
            for sent_vec in sop_sentence_embeddings[cited_chunk_id]:
                score = _cosine_similarity(step_vec, sent_vec)
                if score > best_cosine:
                    best_cosine = score
                    best_chunk_id = cited_chunk_id

        # 2) NLI — 최적 청크 텍스트와 조치 단계를 비교
        nli_label: str | None = None
        contradiction_detected = False

        if best_chunk_id and best_chunk_id in sop_text_map:
            try:
                result = NLIValidator.predict(
                    hypothesis=action,
                    premise=sop_text_map[best_chunk_id],
                )
                nli_label = result.label
                if result.contradiction_score >= self._threshold:
                    contradiction_detected = True
                    logger.warning({
                        "event": "nli_contradiction_detected",
                        "action": action[:80],
                        "chunk_id": best_chunk_id,
                        "contradiction_score": round(result.contradiction_score, 4),
                    })
            except Exception as exc:
                logger.warning({"event": "nli_predict_error", "error": str(exc)})

        # 3) 최종 grounding_score 결정
        if contradiction_detected:
            grounding_score = 0.0
        elif nli_label == "neutral":
            grounding_score = min(best_cosine, 0.5)
        else:
            grounding_score = best_cosine

        return StepScore(
            grounding_score=round(grounding_score, 4),
            best_chunk_id=best_chunk_id,
            nli_label=nli_label,
            contradiction_detected=contradiction_detected,
        )


def get_strategy(nli_enabled: bool, contradiction_threshold: float = 0.5) -> ValidationStrategy:
    if nli_enabled:
        return NLIHybridStrategy(contradiction_threshold=contradiction_threshold)
    return CosineStrategy()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
