"""NLI 검증 전략 단위 테스트.

NLIValidator 자체는 외부 모델 의존이므로 mock 처리.
전략 인터페이스(CosineStrategy, NLIHybridStrategy) 및 contradiction 라우팅 로직을 검증.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.validation_strategy import (
    CosineStrategy,
    NLIHybridStrategy,
    StepScore,
    _cosine_similarity,
    get_strategy,
)
from core.nli_validator import NLIResult


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _unit_vec(dim: int, idx: int) -> list[float]:
    v = [0.0] * dim
    v[idx % dim] = 1.0
    return v


_SOP_EMBEDDINGS = {
    "chunk-A": _unit_vec(4, 0),
    "chunk-B": _unit_vec(4, 1),
}
_SOP_SENTENCE_EMBEDDINGS: dict[str, list[list[float]]] = {}
_SOP_TEXT_MAP = {
    "chunk-A": "Shut down the machine before any inspection.",
    "chunk-B": "Replace the worn tool after stopping the spindle.",
}

_HIGH_SIM_VEC = _unit_vec(4, 0)   # chunk-A와 코사인=1.0
_LOW_SIM_VEC = _unit_vec(4, 2)    # 모든 청크와 코사인=0.0


# ── _cosine_similarity ────────────────────────────────────────────────────────

def test_cosine_identical():
    v = [1.0, 0.0, 0.0]
    assert _cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_orthogonal():
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_zero_vector():
    assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


# ── get_strategy ──────────────────────────────────────────────────────────────

def test_get_strategy_cosine():
    s = get_strategy(nli_enabled=False)
    assert isinstance(s, CosineStrategy)


def test_get_strategy_nli_hybrid():
    s = get_strategy(nli_enabled=True)
    assert isinstance(s, NLIHybridStrategy)


# ── CosineStrategy ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cosine_strategy_high_similarity():
    strategy = CosineStrategy()
    result = await strategy.score_step(
        action="Inspect spindle while running",
        step_vec=_HIGH_SIM_VEC,
        sop_embeddings=_SOP_EMBEDDINGS,
        sop_sentence_embeddings=_SOP_SENTENCE_EMBEDDINGS,
        sop_text_map=_SOP_TEXT_MAP,
        cited_chunk_id=None,
    )
    assert result.grounding_score == pytest.approx(1.0)
    assert result.best_chunk_id == "chunk-A"
    assert result.nli_label is None
    assert result.contradiction_detected is False


@pytest.mark.asyncio
async def test_cosine_strategy_low_similarity():
    strategy = CosineStrategy()
    result = await strategy.score_step(
        action="Unrelated action",
        step_vec=_LOW_SIM_VEC,
        sop_embeddings=_SOP_EMBEDDINGS,
        sop_sentence_embeddings=_SOP_SENTENCE_EMBEDDINGS,
        sop_text_map=_SOP_TEXT_MAP,
        cited_chunk_id=None,
    )
    assert result.grounding_score == pytest.approx(0.0)
    assert result.contradiction_detected is False


# ── NLIHybridStrategy ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_nli_hybrid_contradiction_overrides_high_cosine():
    """코사인=1.0이어도 contradiction 검출 시 grounding_score=0.0."""
    contradiction_result = NLIResult(
        label="contradiction",
        contradiction_score=0.92,
        entailment_score=0.05,
        neutral_score=0.03,
    )
    strategy = NLIHybridStrategy(contradiction_threshold=0.5)
    with patch("core.nli_validator.NLIValidator.predict", return_value=contradiction_result):
        result = await strategy.score_step(
            action="Inspect spindle while the machine is running at full speed",
            step_vec=_HIGH_SIM_VEC,
            sop_embeddings=_SOP_EMBEDDINGS,
            sop_sentence_embeddings=_SOP_SENTENCE_EMBEDDINGS,
            sop_text_map=_SOP_TEXT_MAP,
            cited_chunk_id=None,
        )

    assert result.grounding_score == 0.0
    assert result.contradiction_detected is True
    assert result.nli_label == "contradiction"


@pytest.mark.asyncio
async def test_nli_hybrid_neutral_clamps_score():
    """neutral 판정 시 grounding_score가 0.5로 클램프된다."""
    neutral_result = NLIResult(
        label="neutral",
        contradiction_score=0.05,
        entailment_score=0.20,
        neutral_score=0.75,
    )
    strategy = NLIHybridStrategy(contradiction_threshold=0.5)
    with patch("core.nli_validator.NLIValidator.predict", return_value=neutral_result):
        result = await strategy.score_step(
            action="Calibrate the temperature sensor",
            step_vec=_HIGH_SIM_VEC,
            sop_embeddings=_SOP_EMBEDDINGS,
            sop_sentence_embeddings=_SOP_SENTENCE_EMBEDDINGS,
            sop_text_map=_SOP_TEXT_MAP,
            cited_chunk_id=None,
        )

    assert result.grounding_score <= 0.5
    assert result.contradiction_detected is False
    assert result.nli_label == "neutral"


@pytest.mark.asyncio
async def test_nli_hybrid_entailment_keeps_cosine_score():
    """entailment 판정 시 코사인 점수를 그대로 사용한다."""
    entailment_result = NLIResult(
        label="entailment",
        contradiction_score=0.02,
        entailment_score=0.95,
        neutral_score=0.03,
    )
    strategy = NLIHybridStrategy(contradiction_threshold=0.5)
    with patch("core.nli_validator.NLIValidator.predict", return_value=entailment_result):
        result = await strategy.score_step(
            action="Stop the machine and replace the worn tool",
            step_vec=_HIGH_SIM_VEC,
            sop_embeddings=_SOP_EMBEDDINGS,
            sop_sentence_embeddings=_SOP_SENTENCE_EMBEDDINGS,
            sop_text_map=_SOP_TEXT_MAP,
            cited_chunk_id=None,
        )

    assert result.grounding_score == pytest.approx(1.0)
    assert result.contradiction_detected is False
    assert result.nli_label == "entailment"


@pytest.mark.asyncio
async def test_nli_hybrid_fallback_on_error():
    """NLI 예외 발생 시 코사인 점수를 그대로 반환한다."""
    strategy = NLIHybridStrategy(contradiction_threshold=0.5)
    with patch("core.nli_validator.NLIValidator.predict", side_effect=RuntimeError("model load error")):
        result = await strategy.score_step(
            action="Stop the machine",
            step_vec=_HIGH_SIM_VEC,
            sop_embeddings=_SOP_EMBEDDINGS,
            sop_sentence_embeddings=_SOP_SENTENCE_EMBEDDINGS,
            sop_text_map=_SOP_TEXT_MAP,
            cited_chunk_id=None,
        )

    assert result.grounding_score == pytest.approx(1.0)
    assert result.contradiction_detected is False
    assert result.nli_label is None


# ── conflict_case_nli.json 회귀 테스트 ────────────────────────────────────────

def test_conflict_case_nli_json_structure():
    """data/conflict_case_nli.json이 올바른 구조를 가지는지 확인한다."""
    path = Path(__file__).parent.parent / "data" / "conflict_case_nli.json"
    assert path.exists(), "conflict_case_nli.json이 없습니다"

    data = json.loads(path.read_text())
    assert "cases" in data
    for case in data["cases"]:
        assert "id" in case
        assert "sop_chunk" in case
        assert "action_step" in case
        assert "expected_nli" in case
        assert case["expected_nli"] in ("contradiction", "entailment", "neutral")


def test_conflict_case_nli_contradiction_count():
    """합성 케이스 중 contradiction이 코사인 오판(APPROVE) 케이스와 일치하는지 확인."""
    path = Path(__file__).parent.parent / "data" / "conflict_case_nli.json"
    data = json.loads(path.read_text())

    contradiction_cases = [c for c in data["cases"] if c["expected_nli"] == "contradiction"]
    cosine_false_approve = [
        c for c in contradiction_cases
        if c.get("expected_recommendation_cosine") == "APPROVE"
    ]
    assert len(cosine_false_approve) >= 3, "코사인 오판 케이스가 3개 이상이어야 합니다"
    assert data["summary"]["nli_correct_reject"] == len(cosine_false_approve)


# ── NLIResult 단위 테스트 ─────────────────────────────────────────────────────

def test_nli_result_is_contradiction_true():
    r = NLIResult(label="contradiction", contradiction_score=0.9, entailment_score=0.05, neutral_score=0.05)
    assert r.is_contradiction is True


def test_nli_result_is_contradiction_false():
    r = NLIResult(label="entailment", contradiction_score=0.05, entailment_score=0.9, neutral_score=0.05)
    assert r.is_contradiction is False
