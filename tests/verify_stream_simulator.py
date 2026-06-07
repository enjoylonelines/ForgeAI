"""Verify stream_simulator._compute_metrics logic against known fixtures.

DONE WHEN criteria being checked:
  [1] lead_time = distance from last preceding WARNING/CRITICAL to failure row
  [2] false_alarm_count = WARNING/CRITICAL not followed by failure within lookahead rows
  [3] early_warning_count ≥ 1 when warning precedes failure
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")
from stream_simulator import RowResult, _compute_metrics


def _make_results(risk_levels: list[str]) -> list[RowResult]:
    return [
        RowResult(i, f"EQ-{i}", 0, r, r == "SAFE", 0.1)
        for i, r in enumerate(risk_levels)
    ]


def test_lead_time_basic() -> None:
    """WARNING at row 3, failure at row 7 → lead_time = 4."""
    risks = ["SAFE", "SAFE", "SAFE", "WARNING", "SAFE", "SAFE", "SAFE", "SAFE"]
    failures = [0, 0, 0, 0, 0, 0, 0, 1]
    results = _make_results(risks)

    lead_times, _ = _compute_metrics(results, failures, lookahead=10)
    assert lead_times == [4], f"Expected [4], got {lead_times}"
    print("[PASS] lead_time basic: WARNING@3 → failure@7 = lead_time 4")


def test_lead_time_no_preceding_warning() -> None:
    """Failure with no preceding WARNING → lead_times empty."""
    risks = ["SAFE", "SAFE", "SAFE", "SAFE"]
    failures = [0, 0, 0, 1]
    results = _make_results(risks)

    lead_times, _ = _compute_metrics(results, failures, lookahead=10)
    assert lead_times == [], f"Expected [], got {lead_times}"
    print("[PASS] lead_time no warning: no preceding WARNING → N/A")


def test_false_alarm_within_lookahead() -> None:
    """WARNING at row 2, failure at row 5, lookahead=10 → NOT false alarm."""
    risks = ["SAFE", "SAFE", "WARNING", "SAFE", "SAFE", "SAFE"]
    failures = [0, 0, 0, 0, 0, 1]
    results = _make_results(risks)

    _, false_alarms = _compute_metrics(results, failures, lookahead=10)
    assert false_alarms == 0, f"Expected 0, got {false_alarms}"
    print("[PASS] false_alarm within lookahead: failure at row 5, WARNING@2 → not false alarm")


def test_false_alarm_outside_lookahead() -> None:
    """WARNING at row 1, no failure within 3 rows → IS false alarm (lookahead=3)."""
    risks = ["SAFE", "WARNING", "SAFE", "SAFE", "SAFE", "SAFE"]
    failures = [0, 0, 0, 0, 0, 1]
    results = _make_results(risks)

    _, false_alarms = _compute_metrics(results, failures, lookahead=3)
    assert false_alarms == 1, f"Expected 1, got {false_alarms}"
    print("[PASS] false_alarm outside lookahead: failure@5 outside window of WARNING@1 (lookahead=3)")


def test_multiple_failures_multiple_lead_times() -> None:
    """Two failure events each preceded by a WARNING."""
    risks = ["WARNING", "SAFE", "SAFE", "SAFE", "WARNING", "SAFE", "SAFE"]
    failures = [0, 0, 1, 0, 0, 0, 1]
    results = _make_results(risks)

    lead_times, _ = _compute_metrics(results, failures, lookahead=5)
    assert lead_times == [2, 2], f"Expected [2, 2], got {lead_times}"
    print(f"[PASS] multiple failures: lead_times={lead_times}")


def test_break_metric_reacts() -> None:
    """Break test: if all SAFE → lead_times empty AND false_alarm=0."""
    risks = ["SAFE"] * 10
    failures = [0] * 9 + [1]
    results = _make_results(risks)

    lead_times, false_alarms = _compute_metrics(results, failures, lookahead=10)
    assert lead_times == [], f"Break test: expected [] but got {lead_times}"
    assert false_alarms == 0, f"Break test: expected 0 but got {false_alarms}"
    print("[PASS] break test: all-SAFE → lead_times=[], false_alarm=0 (metric reacts to absence of WARNING)")


if __name__ == "__main__":
    tests = [
        test_lead_time_basic,
        test_lead_time_no_preceding_warning,
        test_false_alarm_within_lookahead,
        test_false_alarm_outside_lookahead,
        test_multiple_failures_multiple_lead_times,
        test_break_metric_reacts,
    ]

    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"[FAIL] {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"[ERROR] {t.__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
