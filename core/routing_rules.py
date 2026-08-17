from __future__ import annotations

from models.routing import RoutingDecision, RoutingInput

# 우선순위 순서로 평가 — 먼저 매칭된 규칙이 적용됨
# R-C1 (D5-C): CRITICAL + verdict_conflict → ESCALATE
# R-C2 (D5-C): WARNING + verdict_conflict → HUMAN_REVIEW
# R-1 (P-A):   CRITICAL → ESCALATE (AUTO 금지)
# R-2 (C-6):   빈 행동 계획 → ESCALATE
# R-3 (B-3):   재시도 소진 + REJECT → ESCALATE
# R-F1:        tool/dependency/grounding degraded → HUMAN_REVIEW
# R-F2:        grounding contradiction → ESCALATE
# R-4:         SAFE early-exit → AUTO
# R-5:         이상 없음 → AUTO
# R-6:         APPROVE → AUTO, REVIEW → HUMAN_REVIEW


_HUMAN_REVIEW_FAILURES = {
    "unknown_tool",
    "invalid_tool_arguments",
    "max_iterations_exceeded",
    "validator_degraded",
    "empty_sop_context",
    "human_review_required",
    "live_eval_not_run",
}

_ESCALATE_FAILURES = {
    "grounding_contradiction",
}


def apply_routing_rules(inp: RoutingInput) -> RoutingDecision:
    if inp.verdict_conflict and inp.risk_level == "CRITICAL":
        return RoutingDecision(
            route="ESCALATE",
            matched_rule="R-C1",
            reason="CRITICAL + verdict_conflict: rule 판정과 perception 불일치, 즉시 에스컬레이션",
        )

    if inp.verdict_conflict and inp.risk_level == "WARNING":
        return RoutingDecision(
            route="HUMAN_REVIEW",
            matched_rule="R-C2",
            reason="WARNING + verdict_conflict: rule 판정과 perception 불일치, 인간 검토 필요",
        )

    if inp.risk_level == "CRITICAL":
        return RoutingDecision(
            route="ESCALATE",
            matched_rule="R-1",
            reason="CRITICAL 위험: AUTO 처리 금지, 관리자 에스컬레이션",
        )

    if inp.plan_step_count == 0 and inp.recommendation is not None:
        return RoutingDecision(
            route="ESCALATE",
            matched_rule="R-2",
            reason="빈 행동 계획: 실행 가능한 단계 없음, 수동 개입 필요",
        )

    if inp.retry_count >= inp.max_retries and inp.recommendation == "REJECT":
        return RoutingDecision(
            route="ESCALATE",
            matched_rule="R-3",
            reason=f"재시도 소진 ({inp.retry_count}/{inp.max_retries}): 검증 REJECT 반복, 에스컬레이션",
        )

    if inp.failure_reason in _ESCALATE_FAILURES:
        return RoutingDecision(
            route="ESCALATE",
            matched_rule="R-F2",
            reason=f"차단 실패 신호({inp.failure_reason}): 자동 처리 금지, 에스컬레이션",
        )

    if inp.failure_reason in _HUMAN_REVIEW_FAILURES:
        return RoutingDecision(
            route="HUMAN_REVIEW",
            matched_rule="R-F1",
            reason=f"검토 필요 실패 신호({inp.failure_reason}): 자동 처리 금지, 인간 검토 필요",
        )

    if inp.risk_level == "SAFE":
        return RoutingDecision(
            route="AUTO",
            matched_rule="R-4",
            reason="SAFE: 위험 없음, 자동 처리",
        )

    if not inp.has_anomaly:
        return RoutingDecision(
            route="AUTO",
            matched_rule="R-5",
            reason="이상 없음: 정상 운전 상태, 자동 처리",
        )

    if inp.recommendation == "REVIEW":
        return RoutingDecision(
            route="HUMAN_REVIEW",
            matched_rule="R-6",
            reason="검증 REVIEW: 자동 처리 금지, 인간 검토 필요",
        )

    if inp.recommendation == "APPROVE":
        return RoutingDecision(
            route="AUTO",
            matched_rule="R-6",
            reason="검증 APPROVE: 계획 유효, 자동 처리",
        )

    return RoutingDecision(
        route="ESCALATE",
        matched_rule="R-F",
        reason="매칭 규칙 없음: 안전 기본값으로 에스컬레이션",
    )
