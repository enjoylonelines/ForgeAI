from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from scripts.eval_agent_reliability import evaluate_case, load_cases, run_eval, run_live_api_eval


ROOT = Path(__file__).resolve().parent.parent
CASE_PATH = ROOT / "data" / "eval" / "agent_reliability_cases.jsonl"


def _case(case_id: str) -> dict:
    return next(case for case in load_cases(CASE_PATH) if case["case_id"] == case_id)


def test_evaluator_loads_all_versioned_cases():
    cases = load_cases(CASE_PATH)

    assert len(cases) == 24
    assert cases[0]["case_id"] == "AR-001"


def test_evaluator_uses_current_routing_rules_for_routes():
    result = evaluate_case(_case("AR-003"))

    assert result["actual_route"] == "ESCALATE"
    assert result["expected_route"] == "ESCALATE"
    assert result["matched_rule"] == "R-1"
    assert result["route_ok"] is True


def test_evaluator_routes_review_to_human_review():
    result = evaluate_case(_case("AR-014"))

    assert result["expected_route"] == "HUMAN_REVIEW"
    assert result["actual_route"] == "HUMAN_REVIEW"
    assert result["matched_rule"] == "R-F1"
    assert result["unsafe_auto"] is False


def test_evaluator_counts_unknown_tools_as_tool_set_failures():
    result = evaluate_case(_case("AR-006"))

    assert result["unknown_tools"] == ["nonexistent_tool"]
    assert result["exact_tool_set_ok"] is False


def test_evaluator_counts_invalid_argument_cases_without_zero_filling():
    result = evaluate_case(_case("AR-007"))

    assert result["invalid_args_detected"] is True
    assert result["expected_failure_reason"] == "invalid_tool_arguments"


def test_evaluator_reports_public_denominators_and_failures():
    report = run_eval(CASE_PATH)
    summary = report["summary"]
    metrics = summary["metrics"]
    observability = report["observability"]

    assert summary["total_cases"] == 24
    assert summary["evaluated_cases"] == 23
    assert summary["skipped_case_ids"] == ["AR-023"]
    assert summary["denominators"]["route_cases"] == 23
    assert metrics["required_tool_recall_pct"] is not None
    assert metrics["unsafe_auto_count"] == 0
    assert summary["failure_case_ids"]["unsafe_auto"] == []
    assert "AR-008" in summary["failure_case_ids"]["max_iteration"]
    assert observability["mode"] == "mock"
    assert observability["latency"]["status"] == "unavailable"
    assert observability["latency"]["threshold_status"] == "not_thresholded"
    assert observability["latency"]["case_ids"] == ["AR-020"]
    assert observability["token_usage"]["status"] == "unavailable"
    assert observability["token_usage"]["total_tokens"] is None
    assert observability["token_usage"]["unavailable_is_not_zero"] is True
    assert observability["token_usage"]["case_ids"] == ["AR-021"]
    assert observability["monetary_cost"]["status"] == "unavailable"
    assert observability["monetary_cost"]["amount"] is None
    assert observability["monetary_cost"]["case_ids"] == ["AR-022"]


def test_evaluator_output_is_json_serializable(tmp_path):
    report = run_eval(CASE_PATH)
    out = tmp_path / "agent_reliability_mock.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["mode"] == "mock"
    assert loaded["summary"]["total_cases"] == 24


def test_live_api_eval_records_latency_and_usage_without_real_network(monkeypatch):
    fake_settings = MagicMock(
        llm_mode="api",
        llm_api_chat_model="gpt-test",
    )
    fake_model = MagicMock()
    fake_model.invoke.return_value = AIMessage(
        content="ForgeAI live API reliability smoke OK",
        response_metadata={
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 6,
                "total_tokens": 16,
            }
        },
    )

    with patch("scripts.eval_agent_reliability.get_settings", return_value=fake_settings), \
         patch("scripts.eval_agent_reliability.get_chat_llm", return_value=fake_model):
        report = run_live_api_eval(CASE_PATH)

    assert report["mode"] == "live_api"
    assert report["summary"]["passed_cases"] == 1
    assert report["summary"]["latency_observed"] is True
    assert report["summary"]["token_usage_observed"] is True
    assert report["result"]["status"] == "passed"
    assert report["result"]["response_ok"] is True
    assert report["result"]["usage"]["total_tokens"] == 16
    assert report["observability"]["latency"]["status"] == "observed"
    assert report["observability"]["latency"]["latency_ms"] is not None
    assert report["observability"]["latency"]["threshold_status"] == "not_thresholded"
    assert report["observability"]["token_usage"]["status"] == "observed"
    assert report["observability"]["token_usage"]["total_tokens"] == 16
    assert report["observability"]["monetary_cost"]["status"] == "unavailable"
    assert report["observability"]["monetary_cost"]["amount"] is None


def test_live_api_eval_fails_closed_when_not_in_api_mode():
    fake_settings = MagicMock(
        llm_mode="ollama",
        llm_api_chat_model="gpt-test",
    )

    with patch("scripts.eval_agent_reliability.get_settings", return_value=fake_settings):
        report = run_live_api_eval(CASE_PATH)

    assert report["summary"]["failed_cases"] == 1
    assert report["result"]["status"] == "failed"
    assert report["result"]["failure_reason"] == "live_api_failed"
    assert report["result"]["error_type"] == "RuntimeError"
    assert report["observability"]["latency"]["status"] == "observed"
    assert report["observability"]["token_usage"]["status"] == "unavailable"
    assert report["observability"]["monetary_cost"]["status"] == "unavailable"
