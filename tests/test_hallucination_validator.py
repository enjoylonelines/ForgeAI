from __future__ import annotations

import math
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hallucination_validator import HallucinationValidatorAgent
from agents.validation_strategy import _cosine_similarity
from models.action_plan import ActionPlan, ActionStep
from models.sop_context import SOPContext
from models.validation_result import ValidationResult


def test_cosine_similarity_identical():
    vec = [1.0, 0.0, 0.0]
    assert math.isclose(_cosine_similarity(vec, vec), 1.0, abs_tol=1e-9)


def test_cosine_similarity_orthogonal():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert math.isclose(_cosine_similarity(a, b), 0.0, abs_tol=1e-9)


def test_cosine_similarity_zero_vector():
    assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


async def test_validator_approve(mock_ollama_embed, mock_chroma_collection, sample_action_plan, sample_sop_context, correlation_id):
    mock_ollama_embed.aembed_query.return_value = [1.0] + [0.0] * 767

    col = mock_chroma_collection
    col.get.return_value = {
        "ids": [
            "SOP-MNT-001-tool-wear-failure.md::chunk::2",
            "SOP-MNT-001-tool-wear-failure.md::chunk::3",
        ],
        "embeddings": [
            [1.0] + [0.0] * 767,
            [1.0] + [0.0] * 767,
        ],
    }

    agent = HallucinationValidatorAgent()
    result = await agent.run(sample_action_plan, sample_sop_context, correlation_id)

    assert result.overall_grounding_score >= 0.85
    assert result.recommendation == "APPROVE"
    assert result.is_valid is True
    assert result.correlation_id == correlation_id


@pytest.mark.slow
async def test_validator_reject_empty_sop(sample_action_plan, correlation_id):
    empty_sop = SOPContext(equipment_id="M-12345", query_used="", chunks=[], correlation_id=correlation_id)

    mock_emb = MagicMock()
    mock_emb.aembed_query = AsyncMock(return_value=[1.0] + [0.0] * 767)

    with patch("agents.hallucination_validator.get_sop_collection"), \
         patch("agents.hallucination_validator.get_embeddings", return_value=mock_emb):
        agent = HallucinationValidatorAgent()
        result = await agent.run(sample_action_plan, empty_sop, correlation_id)

    assert result.overall_grounding_score == 0.0
    assert result.recommendation == "REJECT"


@pytest.mark.slow
async def test_validator_empty_steps(sample_sop_context, correlation_id):
    empty_plan = ActionPlan(
        equipment_id="M-12345",
        generated_at=datetime.now(timezone.utc),
        steps=[],
        correlation_id=correlation_id,
    )
    agent = HallucinationValidatorAgent()
    result = await agent.run(empty_plan, sample_sop_context, correlation_id)

    assert result.overall_grounding_score == 0.0
    assert result.recommendation == "REJECT"
    assert result.is_valid is False
    assert result.explanation is not None
