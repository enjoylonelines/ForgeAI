"""NLI cross-encoder 래퍼 — contradiction / entailment / neutral 판정.

cross-encoder/nli-deberta-v3-small 기준 레이블 순서: [contradiction, entailment, neutral]
한국어 SOP가 포함된 환경에서는 NLI_MODEL=MoritzLaurer/mDeBERTa-v3-base-mnli-xnli 권장 (ADR-015).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.config import get_settings
from core.logging import get_logger

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

logger = get_logger(__name__)

_LABELS = ["contradiction", "entailment", "neutral"]


@dataclass
class NLIResult:
    label: str  # "entailment" | "neutral" | "contradiction"
    contradiction_score: float
    entailment_score: float
    neutral_score: float

    @property
    def is_contradiction(self) -> bool:
        return self.label == "contradiction"


class NLIValidator:
    """Lazy-load cross-encoder. 첫 호출 시 모델을 다운로드·캐시한다."""

    _instance: CrossEncoder | None = None
    _loaded_model: str | None = None

    @classmethod
    def _get_model(cls) -> CrossEncoder:
        from sentence_transformers import CrossEncoder

        model_id = get_settings().nli_model
        if cls._instance is None or cls._loaded_model != model_id:
            logger.info({"event": "nli_model_load", "model": model_id})
            cls._instance = CrossEncoder(model_id)
            cls._loaded_model = model_id
        return cls._instance

    @classmethod
    def predict(cls, hypothesis: str, premise: str) -> NLIResult:
        """(hypothesis=조치 단계, premise=SOP 청크) 쌍으로 NLI 판정."""
        model = cls._get_model()
        scores = model.predict([[premise, hypothesis]], apply_softmax=True)[0]
        label = _LABELS[int(scores.argmax())]
        return NLIResult(
            label=label,
            contradiction_score=float(scores[0]),
            entailment_score=float(scores[1]),
            neutral_score=float(scores[2]),
        )

    @classmethod
    def predict_batch(cls, pairs: list[tuple[str, str]]) -> list[NLIResult]:
        """여러 (hypothesis, premise) 쌍을 배치로 처리."""
        model = cls._get_model()
        inputs = [[premise, hypothesis] for hypothesis, premise in pairs]
        batch_scores = model.predict(inputs, apply_softmax=True)
        results = []
        for scores in batch_scores:
            label = _LABELS[int(scores.argmax())]
            results.append(NLIResult(
                label=label,
                contradiction_score=float(scores[0]),
                entailment_score=float(scores[1]),
                neutral_score=float(scores[2]),
            ))
        return results
