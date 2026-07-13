from __future__ import annotations

import pytest

from core.routing_rules import apply_routing_rules
from models.routing import RoutingInput


def _inp(**kwargs) -> RoutingInput:
    defaults = {
        "risk_level": "WARNING",
        "has_anomaly": True,
        "plan_step_count": 2,
        "retry_count": 0,
        "max_retries": 2,
        "recommendation": "APPROVE",
    }
    return RoutingInput(**{**defaults, **kwargs})


# ── 규칙별 기본 케이스 ──────────────────────────────────────────────────────────

def test_r1_critical_escalates():
    d = apply_routing_rules(_inp(risk_level="CRITICAL"))
    assert d.route == "ESCALATE"
    assert d.matched_rule == "R-1"


def test_r2_empty_plan_escalates():
    d = apply_routing_rules(_inp(plan_step_count=0, recommendation="REVIEW"))
    assert d.route == "ESCALATE"
    assert d.matched_rule == "R-2"


def test_r3_max_retries_exhausted_escalates():
    d = apply_routing_rules(_inp(retry_count=2, max_retries=2, recommendation="REJECT"))
    assert d.route == "ESCALATE"
    assert d.matched_rule == "R-3"


def test_r4_safe_auto():
    d = apply_routing_rules(_inp(risk_level="SAFE", has_anomaly=False, recommendation=None))
    assert d.route == "AUTO"
    assert d.matched_rule == "R-4"


def test_r5_no_anomaly_auto():
    d = apply_routing_rules(_inp(has_anomaly=False, recommendation=None))
    assert d.route == "AUTO"
    assert d.matched_rule == "R-5"


def test_r6_approve_auto():
    d = apply_routing_rules(_inp(recommendation="APPROVE"))
    assert d.route == "AUTO"
    assert d.matched_rule == "R-6"


def test_r6_review_auto():
    d = apply_routing_rules(_inp(recommendation="REVIEW"))
    assert d.route == "AUTO"
    assert d.matched_rule == "R-6"


# ── 우선순위 경계 케이스 ────────────────────────────────────────────────────────

def test_r1_beats_r6_critical_with_approve():
    """CRITICAL이면 APPROVE여도 R-1 우선"""
    d = apply_routing_rules(_inp(risk_level="CRITICAL", recommendation="APPROVE"))
    assert d.matched_rule == "R-1"
    assert d.route == "ESCALATE"


def test_r2_beats_r6_empty_plan_with_approve():
    """빈 계획이면 APPROVE여도 R-2 우선"""
    d = apply_routing_rules(_inp(plan_step_count=0, recommendation="APPROVE"))
    assert d.matched_rule == "R-2"
    assert d.route == "ESCALATE"


def test_r3_retry_exhausted_reject_only():
    """재시도 소진이어도 REJECT가 아니면 R-3 미발동"""
    d = apply_routing_rules(_inp(retry_count=2, max_retries=2, recommendation="REVIEW"))
    assert d.matched_rule == "R-6"
    assert d.route == "AUTO"


def test_r3_retry_not_exhausted_no_escalate():
    """retry_count < max_retries이면 R-3 미발동"""
    d = apply_routing_rules(_inp(retry_count=1, max_retries=2, recommendation="REJECT"))
    assert d.matched_rule != "R-3"


def test_r2_no_trigger_when_recommendation_none():
    """recommendation=None이면 빈 계획도 R-2 미발동 (early-exit 경로)"""
    d = apply_routing_rules(_inp(plan_step_count=0, recommendation=None, risk_level="WARNING", has_anomaly=True))
    assert d.matched_rule != "R-2"


def test_r4_safe_beats_r5():
    """SAFE이면 has_anomaly 관계없이 R-4"""
    d = apply_routing_rules(_inp(risk_level="SAFE", has_anomaly=True, recommendation=None))
    assert d.matched_rule == "R-4"


# ── D5-C verdict_conflict 시나리오 테스트 ───────────────────────────────────────

def test_rc1_critical_conflict_escalates():
    """시나리오 1: rule_engine=CRITICAL, perception=이상없음 → ESCALATE(R-C1)"""
    d = apply_routing_rules(_inp(
        risk_level="CRITICAL",
        has_anomaly=False,
        verdict_conflict=True,
        recommendation="APPROVE",
    ))
    assert d.route == "ESCALATE"
    assert d.matched_rule == "R-C1"


def test_rc2_warning_conflict_human_review():
    """시나리오 2: rule_engine=WARNING, perception=이상없음 → HUMAN_REVIEW(R-C2)"""
    d = apply_routing_rules(_inp(
        risk_level="WARNING",
        has_anomaly=False,
        verdict_conflict=True,
        recommendation="APPROVE",
    ))
    assert d.route == "HUMAN_REVIEW"
    assert d.matched_rule == "R-C2"


def test_rc1_beats_r1_with_conflict():
    """CRITICAL+conflict는 R-C1이 R-1보다 먼저 매칭"""
    d = apply_routing_rules(_inp(risk_level="CRITICAL", verdict_conflict=True))
    assert d.matched_rule == "R-C1"


def test_no_conflict_warning_not_human_review():
    """충돌 없는 WARNING+APPROVE는 R-6으로 AUTO"""
    d = apply_routing_rules(_inp(risk_level="WARNING", has_anomaly=True, verdict_conflict=False, recommendation="APPROVE"))
    assert d.route == "AUTO"
    assert d.matched_rule == "R-6"
