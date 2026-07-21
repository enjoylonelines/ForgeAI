"""라우팅 정확도 평가 — data/routing_eval_20cases.csv 기준."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.routing_rules import apply_routing_rules
from models.routing import RoutingInput


def _load_cases(csv_path: Path) -> list[dict]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _row_to_input(row: dict) -> RoutingInput:
    rec = row["recommendation"].strip() or None
    if rec == "":
        rec = None
    return RoutingInput(
        risk_level=row["risk_level"].strip(),
        has_anomaly=row["has_anomaly"].strip().lower() == "true",
        plan_step_count=int(row["plan_step_count"]),
        retry_count=int(row["retry_count"]),
        max_retries=int(row["max_retries"]),
        recommendation=rec,
        verdict_conflict=row["verdict_conflict"].strip().lower() == "true",
    )


def run_eval(csv_path: Path) -> dict:
    cases = _load_cases(csv_path)
    results = []

    for row in cases:
        inp = _row_to_input(row)
        decision = apply_routing_rules(inp)

        expected_route = row["expected_route"].strip()
        expected_rule = row["expected_rule"].strip()

        route_ok = decision.route == expected_route
        rule_ok = decision.matched_rule == expected_rule
        passed = route_ok and rule_ok

        results.append({
            "case_id": row["case_id"],
            "description": row["description"],
            "passed": passed,
            "expected_route": expected_route,
            "actual_route": decision.route,
            "expected_rule": expected_rule,
            "actual_rule": decision.matched_rule,
        })

    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    accuracy = passed_count / total * 100

    return {"total": total, "passed": passed_count, "accuracy": accuracy, "results": results}


def main() -> None:
    csv_path = ROOT / "data" / "routing_eval_20cases.csv"
    if not csv_path.exists():
        print(f"ERROR: {csv_path} 파일을 찾을 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    report = run_eval(csv_path)
    results = report["results"]

    print(f"\n{'케이스':<6} {'결과':<5} {'기대 route':<14} {'실제 route':<14} {'기대 rule':<8} {'실제 rule':<8}  설명")
    print("-" * 100)
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(
            f"{r['case_id']:<6} {mark:<5} "
            f"{r['expected_route']:<14} {r['actual_route']:<14} "
            f"{r['expected_rule']:<8} {r['actual_rule']:<8}  {r['description']}"
        )

    print("-" * 100)
    print(f"\n라우팅 정확도: {report['passed']}/{report['total']} = {report['accuracy']:.1f}%\n")

    if report["accuracy"] < 100.0:
        sys.exit(1)


if __name__ == "__main__":
    main()
