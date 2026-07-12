from __future__ import annotations

from models.routing import RoutingDecision, RoutingInput

# 우선순위 순서로 평가 — 먼저 매칭된 규칙이 적용됨
# R-1 (P-A): CRITICAL은 AUTO 금지 → ESCALATE
# R-2 (C-6): 빈 행동 계획 → ESCALATE
# R-3 (B-3): 재시도 소진 + REJECT → ESCALATE
# R-4: SAFE early-exit → AUTO
# R-5: 이상 없음 → AUTO
# R-6: APPROVE/REVIEW → AUTO


def apply_routing_rules(inp: RoutingInput) -> RoutingDecision:
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

    if inp.recommendation in ("APPROVE", "REVIEW"):
        return RoutingDecision(
            route="AUTO",
            matched_rule="R-6",
            reason=f"검증 {inp.recommendation}: 계획 유효, 자동 처리",
        )

    return RoutingDecision(
        route="ESCALATE",
        matched_rule="R-F",
        reason="매칭 규칙 없음: 안전 기본값으로 에스컬레이션",
    )
