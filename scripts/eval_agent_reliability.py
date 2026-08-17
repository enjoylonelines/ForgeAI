"""Deterministic ForgeAI Agent reliability evaluator.

This evaluator consumes the versioned mock contract in
data/eval/agent_reliability_cases.jsonl. It does not call Ollama, NLI models,
Chroma, Langfuse, external APIs, or live alert/control systems.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.routing_rules import apply_routing_rules
from core.config import get_settings
from core.langchain_client import get_chat_llm
from langchain_core.messages import HumanMessage
from models.routing import RoutingInput

DEFAULT_CASES = ROOT / "data" / "eval" / "agent_reliability_cases.jsonl"
DEFAULT_OUTPUT = ROOT / "output" / "agent_reliability_mock.json"
DEFAULT_LIVE_OUTPUT = ROOT / "output" / "agent_reliability_live_api.json"
LIVE_CASE_ID = "AR-023"
LIVE_PROMPT = "Reply with exactly: ForgeAI live API reliability smoke OK"
UNAVAILABLE_OBSERVABILITY = {
    "latency": {
        "status": "unavailable",
        "latency_ms": None,
        "threshold_ms": None,
        "threshold_status": "not_thresholded",
    },
    "token_usage": {
        "status": "unavailable",
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
    },
    "monetary_cost": {
        "status": "unavailable",
        "amount": None,
        "currency": None,
        "pricing_source": None,
    },
}

KNOWN_TOOLS = {
    "get_sensor_thresholds",
    "calculate_risk_index",
    "alert_maintenance_team",
}
MOCK_MODES = {"mock", "mock_degraded"}


def load_cases(path: Path = DEFAULT_CASES) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_no}: {exc}") from exc
    return cases


def _routing_input(case: dict[str, Any]) -> RoutingInput:
    data = case["input"]
    return RoutingInput(
        risk_level=data.get("risk_level", "UNKNOWN"),
        has_anomaly=bool(data.get("has_anomaly", False)),
        plan_step_count=int(data.get("plan_step_count", 0)),
        retry_count=int(data.get("retry_count", 0)),
        max_retries=int(data.get("max_retries", 2)),
        recommendation=data.get("validator_recommendation"),
        verdict_conflict=bool(data.get("verdict_conflict", False)),
        failure_reason=case.get("expected_failure_reason"),
    )


def _has_invalid_risk_args(case: dict[str, Any]) -> bool:
    values = case["input"].get("sensor_values", {})
    required = ("tool_wear_min", "torque_nm", "rotational_speed_rpm")
    return any(not isinstance(values.get(key), int | float) for key in required)


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    if case["dependency_mode"] not in MOCK_MODES:
        return {
            "case_id": case["case_id"],
            "scenario": case["scenario"],
            "status": "skipped",
            "skip_reason": case["dependency_mode"],
        }

    actual_tools = list(case["input"].get("mock_tool_calls", []))
    actual_tool_set = set(actual_tools)
    required_tools = set(case["required_tools"])
    forbidden_tools = set(case["forbidden_tools"])
    unknown_tools = sorted(actual_tool_set - KNOWN_TOOLS)
    forbidden_called = sorted(actual_tool_set & forbidden_tools)
    missing_required = sorted(required_tools - actual_tool_set)

    decision = apply_routing_rules(_routing_input(case))
    actual_route = decision.route
    expected_route = case["expected_route"]
    max_tool_calls = int(case["max_tool_calls"])
    tool_call_count = len(actual_tools)

    exact_tool_set_ok = (
        not unknown_tools
        and not forbidden_called
        and not missing_required
        and actual_tool_set <= required_tools
    )
    max_iteration_ok = tool_call_count <= max_tool_calls
    route_ok = actual_route == expected_route
    unsafe_auto = expected_route != "AUTO" and actual_route == "AUTO"
    invalid_args_detected = _has_invalid_risk_args(case)

    return {
        "case_id": case["case_id"],
        "scenario": case["scenario"],
        "status": "evaluated",
        "dependency_mode": case["dependency_mode"],
        "covers": case["covers"],
        "required_tools": sorted(required_tools),
        "actual_tools": actual_tools,
        "forbidden_tools": sorted(forbidden_tools),
        "missing_required_tools": missing_required,
        "unknown_tools": unknown_tools,
        "forbidden_tools_called": forbidden_called,
        "tool_call_count": tool_call_count,
        "max_tool_calls": max_tool_calls,
        "exact_tool_set_ok": exact_tool_set_ok,
        "required_tool_hits": len(required_tools & actual_tool_set),
        "required_tool_total": len(required_tools),
        "forbidden_called": bool(forbidden_called),
        "max_iteration_ok": max_iteration_ok,
        "invalid_args_detected": invalid_args_detected,
        "expected_failure_reason": case["expected_failure_reason"],
        "actual_route": actual_route,
        "expected_route": expected_route,
        "matched_rule": decision.matched_rule,
        "route_ok": route_ok,
        "unsafe_auto": unsafe_auto,
    }


def _pct(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return round(float(numerator) / float(denominator) * 100.0, 1)


def _mock_observability(results: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [r for r in results if r["status"] == "evaluated"]
    latency_cases = [
        r for r in evaluated
        if "latency_observability" in r["covers"]
    ]
    token_cases = [
        r for r in evaluated
        if "token_usage_observability" in r["covers"]
    ]
    cost_cases = [
        r for r in evaluated
        if "cost_observability" in r["covers"]
    ]

    return {
        "mode": "mock",
        "latency": {
            **UNAVAILABLE_OBSERVABILITY["latency"],
            "case_ids": [r["case_id"] for r in latency_cases],
            "note": "Mock reliability mode records that latency is expected when available, but does not measure runtime latency.",
        },
        "token_usage": {
            **UNAVAILABLE_OBSERVABILITY["token_usage"],
            "case_ids": [r["case_id"] for r in token_cases],
            "unavailable_is_not_zero": bool(token_cases),
        },
        "monetary_cost": {
            **UNAVAILABLE_OBSERVABILITY["monetary_cost"],
            "case_ids": [r["case_id"] for r in cost_cases],
            "unavailable_is_not_zero": bool(cost_cases),
        },
    }


def _usage_observability(usage: dict[str, Any] | None) -> dict[str, Any]:
    if not usage:
        return dict(UNAVAILABLE_OBSERVABILITY["token_usage"])

    return {
        "status": "observed",
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [r for r in results if r["status"] == "evaluated"]
    skipped = [r for r in results if r["status"] == "skipped"]

    required_hits = sum(r["required_tool_hits"] for r in evaluated)
    required_total = sum(r["required_tool_total"] for r in evaluated)
    forbidden_opportunities = [r for r in evaluated if r["forbidden_tools"]]
    forbidden_called = [r for r in forbidden_opportunities if r["forbidden_called"]]
    invalid_arg_cases = [
        r for r in evaluated
        if r["expected_failure_reason"] == "invalid_tool_arguments"
    ]
    invalid_rejected = [
        r for r in invalid_arg_cases
        if r["invalid_args_detected"] and r["actual_route"] != "AUTO"
    ]
    route_matches = [r for r in evaluated if r["route_ok"]]
    exact_tool_matches = [r for r in evaluated if r["exact_tool_set_ok"]]
    max_iteration_ok = [r for r in evaluated if r["max_iteration_ok"]]
    unsafe_auto = [r for r in evaluated if r["unsafe_auto"]]

    return {
        "total_cases": len(results),
        "evaluated_cases": len(evaluated),
        "skipped_cases": len(skipped),
        "skipped_case_ids": [r["case_id"] for r in skipped],
        "metrics": {
            "exact_tool_set_accuracy_pct": _pct(len(exact_tool_matches), len(evaluated)),
            "required_tool_recall_pct": _pct(required_hits, required_total),
            "forbidden_tool_call_rate_pct": _pct(
                len(forbidden_called), len(forbidden_opportunities)
            ),
            "invalid_argument_rejection_rate_pct": _pct(
                len(invalid_rejected), len(invalid_arg_cases)
            ),
            "max_iteration_compliance_pct": _pct(
                len(max_iteration_ok), len(evaluated)
            ),
            "route_accuracy_pct": _pct(len(route_matches), len(evaluated)),
            "unsafe_auto_count": len(unsafe_auto),
        },
        "denominators": {
            "exact_tool_set_cases": len(evaluated),
            "required_tool_recall_tools": required_total,
            "forbidden_tool_cases": len(forbidden_opportunities),
            "invalid_argument_cases": len(invalid_arg_cases),
            "max_iteration_cases": len(evaluated),
            "route_cases": len(evaluated),
            "unsafe_auto_cases": len(evaluated),
        },
        "failure_case_ids": {
            "tool_set": [
                r["case_id"] for r in evaluated if not r["exact_tool_set_ok"]
            ],
            "forbidden_tool": [r["case_id"] for r in forbidden_called],
            "invalid_argument_rejection": [
                r["case_id"] for r in invalid_arg_cases if r not in invalid_rejected
            ],
            "max_iteration": [
                r["case_id"] for r in evaluated if not r["max_iteration_ok"]
            ],
            "route": [r["case_id"] for r in evaluated if not r["route_ok"]],
            "unsafe_auto": [r["case_id"] for r in unsafe_auto],
        },
    }


def run_eval(case_path: Path = DEFAULT_CASES) -> dict[str, Any]:
    cases = load_cases(case_path)
    results = [evaluate_case(case) for case in cases]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "mock",
        "case_path": str(case_path),
        "summary": summarize(results),
        "observability": _mock_observability(results),
        "results": results,
        "limits": [
            "No live Ollama, NLI model, Chroma reindexing, Langfuse, external API, real alert, or live control action was executed.",
            "Routes are produced by the current apply_routing_rules implementation; evaluator logic does not override product routing.",
            "Latency, token usage, and monetary cost are reported as unavailable in mock mode rather than zero-filled.",
        ],
    }


def run_live_api_eval(case_path: Path = DEFAULT_CASES) -> dict[str, Any]:
    cases = load_cases(case_path)
    live_case = next((case for case in cases if case["case_id"] == LIVE_CASE_ID), None)
    if live_case is None:
        raise ValueError(f"Missing live API case: {LIVE_CASE_ID}")

    settings = get_settings()
    started = time.perf_counter()
    result: dict[str, Any] = {
        "case_id": live_case["case_id"],
        "scenario": live_case["scenario"],
        "dependency_mode": live_case["dependency_mode"],
        "status": "failed",
        "llm_mode": settings.llm_mode,
        "model": settings.llm_api_chat_model,
        "latency_ms": None,
        "usage": None,
        "token_usage_status": UNAVAILABLE_OBSERVABILITY["token_usage"]["status"],
        "monetary_cost_status": UNAVAILABLE_OBSERVABILITY["monetary_cost"]["status"],
    }

    try:
        if settings.llm_mode != "api":
            raise RuntimeError("Live API reliability smoke requires LLM_MODE=api")
        response = get_chat_llm().invoke([HumanMessage(content=LIVE_PROMPT)])
        latency_ms = round((time.perf_counter() - started) * 1000)
        usage = response.response_metadata.get("usage")
        result.update({
            "status": "passed",
            "latency_ms": latency_ms,
            "response": response.content,
            "expected_response": "ForgeAI live API reliability smoke OK",
            "response_ok": response.content.strip() == "ForgeAI live API reliability smoke OK",
            "usage": usage,
            "token_usage_status": "observed" if usage else "unavailable",
        })
    except Exception as exc:
        result.update({
            "status": "failed",
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "failure_reason": "live_api_failed",
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        })

    observability = {
        "mode": "live_api",
        "latency": {
            "status": "observed" if result.get("latency_ms") is not None else "unavailable",
            "latency_ms": result.get("latency_ms"),
            "threshold_ms": None,
            "threshold_status": "not_thresholded",
        },
        "token_usage": _usage_observability(result.get("usage")),
        "monetary_cost": dict(UNAVAILABLE_OBSERVABILITY["monetary_cost"]),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "live_api",
        "case_path": str(case_path),
        "summary": {
            "total_cases": 1,
            "evaluated_cases": 1,
            "passed_cases": 1 if result["status"] == "passed" and result.get("response_ok") else 0,
            "failed_cases": 0 if result["status"] == "passed" and result.get("response_ok") else 1,
            "latency_observed": observability["latency"]["status"] == "observed",
            "token_usage_observed": observability["token_usage"]["status"] == "observed",
            "monetary_cost_status": observability["monetary_cost"]["status"],
        },
        "observability": observability,
        "result": result,
        "limits": [
            "This live API smoke calls only the configured OpenAI-compatible chat endpoint.",
            "It does not run Ollama, NLI, Chroma reindexing, Langfuse, real alert channels, or live control.",
            "It is not a full ForgePipeline benchmark and does not replace the deterministic mock reliability result.",
            "Monetary cost is not computed from usage because no versioned pricing table is part of this repository contract.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--live-api", action="store_true", help="Run the single opt-in live API smoke case.")
    args = parser.parse_args()

    if args.live_api:
        report = run_live_api_eval(args.cases)
        out = args.out if args.out != DEFAULT_OUTPUT else DEFAULT_LIVE_OUTPUT
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        result = report["result"]
        print(
            "Agent reliability live API smoke: "
            f"status={result['status']}, "
            f"response_ok={result.get('response_ok')}, "
            f"latency_ms={result.get('latency_ms')}, "
            f"token_usage={result.get('token_usage_status')}"
        )
        print(f"Report: {out}")
        return

    report = run_eval(args.cases)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    metrics = report["summary"]["metrics"]
    print(
        "Agent reliability mock eval: "
        f"{report['summary']['evaluated_cases']} evaluated, "
        f"{report['summary']['skipped_cases']} skipped"
    )
    print(
        "route_accuracy="
        f"{metrics['route_accuracy_pct']}%, "
        "required_tool_recall="
        f"{metrics['required_tool_recall_pct']}%, "
        "unsafe_auto_count="
        f"{metrics['unsafe_auto_count']}"
    )
    print(f"Report: {args.out}")


if __name__ == "__main__":
    main()
