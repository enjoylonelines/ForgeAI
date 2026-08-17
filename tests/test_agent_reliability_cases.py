from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CASE_PATH = ROOT / "data" / "eval" / "agent_reliability_cases.jsonl"

REQUIRED_FIELDS = {
    "case_id",
    "scenario",
    "input",
    "dependency_mode",
    "required_tools",
    "forbidden_tools",
    "expected_route",
    "max_tool_calls",
    "expected_failure_reason",
    "evidence_source",
    "covers",
}
KNOWN_TOOLS = {
    "get_sensor_thresholds",
    "calculate_risk_index",
    "alert_maintenance_team",
}
VALID_ROUTES = {"AUTO", "HUMAN_REVIEW", "ESCALATE"}
VALID_DEPENDENCY_MODES = {"mock", "mock_degraded", "live_opt_in"}


def _cases() -> list[dict]:
    assert CASE_PATH.exists(), f"missing case file: {CASE_PATH}"
    rows = []
    for line_no, line in enumerate(CASE_PATH.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise AssertionError(f"invalid JSON on line {line_no}: {exc}") from exc
    return rows


def test_agent_reliability_cases_have_required_schema():
    cases = _cases()
    assert len(cases) >= 20

    for case in cases:
        assert REQUIRED_FIELDS <= case.keys()
        assert case["case_id"].startswith("AR-")
        assert isinstance(case["input"], dict)
        assert case["dependency_mode"] in VALID_DEPENDENCY_MODES
        assert case["expected_route"] in VALID_ROUTES
        assert isinstance(case["max_tool_calls"], int)
        assert case["max_tool_calls"] >= 0
        assert case["evidence_source"].strip()
        assert case["covers"]


def test_agent_reliability_case_ids_are_unique():
    case_ids = [case["case_id"] for case in _cases()]
    assert len(case_ids) == len(set(case_ids))


def test_required_and_forbidden_tools_are_known_and_disjoint():
    for case in _cases():
        required = set(case["required_tools"])
        forbidden = set(case["forbidden_tools"])
        assert required <= KNOWN_TOOLS
        assert forbidden <= KNOWN_TOOLS
        assert required.isdisjoint(forbidden)


def test_safety_cases_do_not_expect_auto_route():
    safety_tags = {
        "unsafe_auto",
        "unknown_tool",
        "invalid_argument",
        "max_iteration",
        "dependency_degraded",
        "grounding",
    }

    for case in _cases():
        covers = set(case["covers"])
        if covers & safety_tags:
            assert case["expected_route"] != "AUTO", case["case_id"]


def test_observability_unavailable_values_are_explicit_failure_reasons():
    unavailable_cases = [
        case for case in _cases()
        if {"token_usage_observability", "cost_observability"} & set(case["covers"])
    ]
    assert unavailable_cases

    for case in unavailable_cases:
        assert case["expected_failure_reason"] in {
            "token_usage_unavailable",
            "monetary_cost_unavailable",
        }


def test_minimum_required_coverage_is_present():
    covers = set()
    for case in _cases():
        covers.update(case["covers"])

    assert {
        "tool_selection",
        "required_tool_recall",
        "forbidden_tool",
        "unknown_tool",
        "invalid_argument",
        "max_iteration",
        "grounding",
        "routing",
        "unsafe_auto",
        "latency_observability",
        "token_usage_observability",
        "cost_observability",
        "live_reliability",
    } <= covers
