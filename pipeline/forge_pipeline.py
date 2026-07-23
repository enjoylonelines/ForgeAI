from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Annotated, Any

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from agents.action_plan_agent import ActionPlanAgent
from agents.diagnostic_agent import DiagnosticAgent
from agents.hallucination_validator import HallucinationValidatorAgent
from agents.perception_agent import PerceptionAgent
from agents.sop_rag_agent import SOPRAGAgent
from core.config import get_settings
from core import decision_logger
from core.langfuse_client import get_langfuse
from core.logging import get_logger
from core.rule_engine import assess_risk
from core import ml_predictor
from models.decision_event import DecisionEvent
from models.action_plan import ActionPlan
from models.anomaly_report import AnomalyReport
from models.diagnostic_result import DiagnosticResult
from models.equipment_log import EquipmentLog
from models.risk_assessment import RiskAssessment
from models.routing import RoutingDecision, RoutingInput
from models.sop_context import SOPContext
from models.validation_result import ValidationResult
from core.routing_rules import apply_routing_rules
from control.bridge import execute_control_plan

logger = get_logger(__name__)


class PipelineMetrics(BaseModel):
    risk_level: str = "UNKNOWN"
    early_exit: bool = False
    retry_count: int = 0
    stages_completed: list[str] = []
    mode: str = "full"  # "full" | "rule-only"


class PipelineResult(BaseModel):
    correlation_id: str
    risk_assessment: RiskAssessment | None = None
    anomaly_report: AnomalyReport | None = None
    diagnostic_result: DiagnosticResult | None = None
    sop_context: SOPContext | None = None
    action_plan: ActionPlan | None = None
    validation_result: ValidationResult | None = None
    routing_decision: RoutingDecision | None = None
    metrics: PipelineMetrics = Field(default_factory=PipelineMetrics)
    pipeline_completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── LangGraph state ────────────────────────────────────────────────────────────

class _GraphState(BaseModel):
    log: EquipmentLog
    correlation_id: str

    risk_assessment: RiskAssessment | None = None
    anomaly_report: AnomalyReport | None = None
    diagnostic_result: DiagnosticResult | None = None
    sop_context: SOPContext | None = None
    action_plan: ActionPlan | None = None
    validation_result: ValidationResult | None = None

    retry_count: int = 0
    previous_feedback: str | None = None
    stages_completed: list[str] = []
    routing_decision: RoutingDecision | None = None


def _apply_routing_bridge(decision: RoutingDecision, state: _GraphState) -> None:
    """AUTO → dry-run 브릿지, ESCALATE → NOTIFY_SUPERVISOR 로그."""
    if decision.route == "AUTO" and state.action_plan and state.action_plan.steps:
        try:
            execute_control_plan(state.action_plan, state.correlation_id, dry_run=True)
        except Exception as exc:
            logger.warning({
                "event": "routing_bridge_dry_run_failed",
                "correlation_id": state.correlation_id,
                "error": str(exc),
            })
    elif decision.route == "ESCALATE":
        logger.warning({
            "event": "routing_bridge_escalate",
            "correlation_id": state.correlation_id,
            "command": "NOTIFY_SUPERVISOR",
            "matched_rule": decision.matched_rule,
            "reason": decision.reason,
        })


# ── Pipeline ───────────────────────────────────────────────────────────────────

class ForgePipeline:
    def __init__(self, model: str | None = None) -> None:
        self._perception = PerceptionAgent(model=model)
        self._diagnostic = DiagnosticAgent(model=model)
        self._sop_rag = SOPRAGAgent(model=model)
        self._action_plan = ActionPlanAgent(model=model)
        self._validator = HallucinationValidatorAgent(model=model)
        self._graph = self._build_graph()

    # ── node implementations ───────────────────────────────────────────────────

    async def _node_risk_assessment(self, state: _GraphState) -> dict[str, Any]:
        _t0 = time.perf_counter()
        assessment = assess_risk(state.log, state.correlation_id)
        decision_logger.append(DecisionEvent(
            correlation_id=state.correlation_id,
            stage="rule_engine",
            signals={"risk_level": assessment.risk_level, "failure_type": assessment.failure_type, "triggered": assessment.triggered_failure_types},
            decision=assessment.risk_level,
            reason=f"failure_type={assessment.failure_type}, factors={len(assessment.risk_factors)}",
            duration_ms=(time.perf_counter() - _t0) * 1000,
        ))
        logger.info({
            "event": "risk_assessment_complete",
            "correlation_id": state.correlation_id,
            "equipment_id": state.log.equipment_id,
            "risk_level": assessment.risk_level,
            "risk_factor_count": len(assessment.risk_factors),
        })
        logger.info({
            "event": "pipeline_stage",
            "stage": "01_분류(rule_engine)",
            "correlation_id": state.correlation_id,
            "failure_type": assessment.failure_type,
            "triggered": assessment.triggered_failure_types,
            "risk_level": assessment.risk_level,
        })

        # ADR-013: ML predictor 보조 신호 — rule_engine=SAFE인 경우에만 개입
        _ml_t0 = time.perf_counter()
        ml_proba = ml_predictor.predict_proba(state.log)
        ml_upgraded = False
        if assessment.risk_level == "SAFE" and ml_proba >= ml_predictor.ML_THRESHOLD:
            assessment = assessment.model_copy(update={
                "risk_level": "WARNING",
                "summary": (
                    f"[ML] Potential anomaly detected (proba={ml_proba:.3f} ≥ {ml_predictor.ML_THRESHOLD}). "
                    "No deterministic sensor threshold exceeded — statistical pattern only."
                ),
                "recommended_action": "Schedule preventive inspection within the current shift.",
                "ml_predictor_proba": ml_proba,
                "ml_predictor_upgraded": True,
            })
            ml_upgraded = True
        else:
            assessment = assessment.model_copy(update={"ml_predictor_proba": ml_proba})

        decision_logger.append(DecisionEvent(
            correlation_id=state.correlation_id,
            stage="ml_predictor",
            signals={"ml_proba": round(ml_proba, 4), "threshold": ml_predictor.ML_THRESHOLD, "upgraded": ml_upgraded},
            decision="UPGRADED_TO_WARNING" if ml_upgraded else "NO_CHANGE",
            reason=f"proba={ml_proba:.4f}, threshold={ml_predictor.ML_THRESHOLD}",
            duration_ms=(time.perf_counter() - _ml_t0) * 1000,
        ))
        logger.info({
            "event": "pipeline_stage",
            "stage": "01b_ML예측(ml_predictor)",
            "correlation_id": state.correlation_id,
            "ml_proba": round(ml_proba, 4),
            "ml_upgraded": ml_upgraded,
            "final_risk_level": assessment.risk_level,
        })

        return {
            "risk_assessment": assessment,
            "stages_completed": state.stages_completed + ["risk_assessment"],
        }

    async def _node_perception(self, state: _GraphState) -> dict[str, Any]:
        _t0 = time.perf_counter()
        try:
            report = await self._perception.run(state.log, state.correlation_id)
        except Exception as exc:
            logger.warning({
                "event": "node_perception_failed",
                "correlation_id": state.correlation_id,
                "equipment_id": state.log.equipment_id,
                "error": str(exc),
                "fallback": "has_anomaly=True (conservative)",
            })
            report = AnomalyReport(
                equipment_id=state.log.equipment_id,
                timestamp=state.log.timestamp,
                has_anomaly=True,
                anomalies=[],
                summary="[PERCEPTION FAILED] Assuming anomaly present — manual inspection required.",
                raw_log_snippet="",
                correlation_id=state.correlation_id,
                tags=state.log.tags,
            )
        decision_logger.append(DecisionEvent(
            correlation_id=state.correlation_id,
            stage="perception",
            signals={"has_anomaly": report.has_anomaly, "anomaly_count": len(report.anomalies)},
            decision="ANOMALY_DETECTED" if report.has_anomaly else "NO_ANOMALY",
            reason=report.summary,
            duration_ms=(time.perf_counter() - _t0) * 1000,
        ))
        logger.info({
            "event": "pipeline_stage",
            "stage": "02_이상탐지(perception)",
            "correlation_id": state.correlation_id,
            "has_anomaly": report.has_anomaly,
            "anomaly_count": len(report.anomalies),
            "summary": report.summary,
        })
        return {
            "anomaly_report": report,
            "stages_completed": state.stages_completed + ["perception"],
        }

    async def _node_diagnostic_and_sop_rag(self, state: _GraphState) -> dict[str, Any]:
        """Run diagnostic and SOP-RAG in parallel — both only need anomaly_report."""
        _t0 = time.perf_counter()
        failure_type = (
            state.risk_assessment.failure_type if state.risk_assessment else None
        )
        diagnostic_task = self._diagnostic.run(state.anomaly_report, state.correlation_id)
        sop_rag_task = self._sop_rag.run(state.anomaly_report, failure_type, state.correlation_id)

        diagnostic_result, sop_ctx = await asyncio.gather(
            diagnostic_task, sop_rag_task, return_exceptions=True
        )

        if isinstance(diagnostic_result, BaseException):
            logger.warning({
                "event": "node_diagnostic_failed",
                "correlation_id": state.correlation_id,
                "error": str(diagnostic_result),
                "fallback": "diagnostic_result=None",
            })
            diagnostic_result = None

        if isinstance(sop_ctx, BaseException):
            logger.warning({
                "event": "node_sop_rag_failed",
                "correlation_id": state.correlation_id,
                "error": str(sop_ctx),
                "fallback": "empty SOPContext",
            })
            sop_ctx = SOPContext(
                equipment_id=state.log.equipment_id,
                query_used="[SOPRAGAgent failed]",
                chunks=[],
                correlation_id=state.correlation_id,
            )

        decision_logger.append(DecisionEvent(
            correlation_id=state.correlation_id,
            stage="sop_search",
            signals={"query_used": sop_ctx.query_used, "chunk_count": len(sop_ctx.chunks)},
            decision="CHUNKS_FOUND" if sop_ctx.chunks else "NO_CHUNKS",
            reason=f"top_chunk={sop_ctx.chunks[0].chunk_id if sop_ctx.chunks else None}",
            duration_ms=(time.perf_counter() - _t0) * 1000,
        ))
        logger.info({
            "event": "pipeline_stage",
            "stage": "03_SOP검색(sop_rag)",
            "correlation_id": state.correlation_id,
            "query_used": sop_ctx.query_used,
            "chunk_count": len(sop_ctx.chunks),
            "top_chunk": sop_ctx.chunks[0].chunk_id if sop_ctx.chunks else None,
        })
        return {
            "diagnostic_result": diagnostic_result,
            "sop_context": sop_ctx,
            "stages_completed": state.stages_completed + ["diagnostic", "sop_rag"],
        }

    async def _node_action_plan(self, state: _GraphState) -> dict[str, Any]:
        _t0 = time.perf_counter()
        failure_type = (
            state.risk_assessment.failure_type
            if state.risk_assessment
            else None
        )
        try:
            plan = await self._action_plan.run(
                state.anomaly_report,
                state.sop_context,
                state.correlation_id,
                previous_feedback=state.previous_feedback,
                retry_attempt=state.retry_count,
                failure_type=failure_type,
            )
        except Exception as exc:
            logger.warning({
                "event": "node_action_plan_failed",
                "correlation_id": state.correlation_id,
                "equipment_id": state.log.equipment_id,
                "error": str(exc),
                "fallback": "empty ActionPlan",
            })
            plan = ActionPlan(
                equipment_id=state.log.equipment_id,
                generated_at=datetime.now(timezone.utc),
                steps=[],
                escalation_required=True,
                escalation_reason="[ACTION PLAN FAILED] Manual intervention required.",
                correlation_id=state.correlation_id,
            )
        decision_logger.append(DecisionEvent(
            correlation_id=state.correlation_id,
            stage="action_plan",
            signals={"step_count": len(plan.steps), "escalation_required": plan.escalation_required},
            decision="PLAN_GENERATED" if plan.steps else "FALLBACK",
            reason=f"escalation={plan.escalation_required}, retry={state.retry_count}",
            duration_ms=(time.perf_counter() - _t0) * 1000,
        ))
        logger.info({
            "event": "pipeline_stage",
            "stage": "04_행동계획(action_plan)",
            "correlation_id": state.correlation_id,
            "step_count": len(plan.steps),
            "escalation_required": plan.escalation_required,
            "steps": [s.action[:60] for s in plan.steps],
        })
        return {
            "action_plan": plan,
            "stages_completed": state.stages_completed + ["action_plan"],
        }

    async def _node_validator(self, state: _GraphState) -> dict[str, Any]:
        _t0 = time.perf_counter()
        try:
            result = await self._validator.run(state.action_plan, state.sop_context, state.correlation_id)
        except Exception as exc:
            logger.warning({
                "event": "node_validator_failed",
                "correlation_id": state.correlation_id,
                "equipment_id": state.log.equipment_id,
                "error": str(exc),
                "fallback": "recommendation=REVIEW",
            })
            result = ValidationResult(
                equipment_id=state.log.equipment_id,
                validated_at=datetime.now(timezone.utc),
                overall_grounding_score=0.0,
                is_valid=False,
                step_validations=[],
                ungrounded_steps=[],
                recommendation="REVIEW",
                explanation="[VALIDATOR FAILED] Could not validate plan — manual review required.",
                correlation_id=state.correlation_id,
            )
        decision_logger.append(DecisionEvent(
            correlation_id=state.correlation_id,
            stage="validator",
            signals={"grounding_score": result.overall_grounding_score, "ungrounded_steps": result.ungrounded_steps},
            decision=result.recommendation,
            reason=result.explanation or "",
            duration_ms=(time.perf_counter() - _t0) * 1000,
        ))
        logger.info({
            "event": "pipeline_stage",
            "stage": "05_검증(validator)",
            "correlation_id": state.correlation_id,
            "recommendation": result.recommendation,
            "grounding_score": result.overall_grounding_score,
            "ungrounded_steps": result.ungrounded_steps,
        })
        updates: dict[str, Any] = {
            "validation_result": result,
            "stages_completed": state.stages_completed + ["validator"],
        }
        if result.recommendation == "REJECT":
            feedback_parts = [result.explanation or "Plan did not meet grounding requirements."]
            ungrounded = result.ungrounded_steps
            if ungrounded:
                feedback_parts.append(f"Ungrounded steps: {ungrounded}. Each step must cite a valid SOP chunk_id.")
            updates["previous_feedback"] = " ".join(feedback_parts)
            updates["retry_count"] = state.retry_count + 1
        return updates

    # ── edge conditions ────────────────────────────────────────────────────────

    def _route_after_risk(self, state: _GraphState) -> str:
        _t0 = time.perf_counter()
        next_node = "early_exit" if (state.risk_assessment and state.risk_assessment.risk_level == "SAFE") else "perception"
        decision_logger.append(DecisionEvent(
            correlation_id=state.correlation_id,
            stage="routing",
            signals={"from": "risk_assessment", "risk_level": state.risk_assessment.risk_level if state.risk_assessment else None},
            decision=next_node,
            reason="SAFE→early_exit, else→perception",
            duration_ms=(time.perf_counter() - _t0) * 1000,
        ))
        return next_node

    def _route_after_perception(self, state: _GraphState) -> str:
        _t0 = time.perf_counter()
        next_node = "parallel" if (state.anomaly_report and state.anomaly_report.has_anomaly) else "end_no_anomaly"
        decision_logger.append(DecisionEvent(
            correlation_id=state.correlation_id,
            stage="routing",
            signals={"from": "perception", "has_anomaly": state.anomaly_report.has_anomaly if state.anomaly_report else None},
            decision=next_node,
            reason="has_anomaly→parallel, else→end_no_anomaly",
            duration_ms=(time.perf_counter() - _t0) * 1000,
        ))
        return next_node

    def _route_after_validator(self, state: _GraphState) -> str:
        _t0 = time.perf_counter()
        rec = state.validation_result.recommendation if state.validation_result else "APPROVE"
        if rec in ("APPROVE", "REVIEW"):
            next_node = "end_approved"
        elif state.retry_count < get_settings().pipeline_max_retries:
            next_node = "retry_action_plan"
        else:
            next_node = "end_max_retries"
        decision_logger.append(DecisionEvent(
            correlation_id=state.correlation_id,
            stage="routing",
            signals={"from": "validator", "recommendation": rec, "retry_count": state.retry_count},
            decision=next_node,
            reason=f"rec={rec}, retry={state.retry_count}",
            duration_ms=(time.perf_counter() - _t0) * 1000,
        ))
        return next_node

    # ── routing exit gate ──────────────────────────────────────────────────────

    async def _node_routing(self, state: _GraphState) -> dict[str, Any]:
        _t0 = time.perf_counter()
        s = get_settings()
        risk_level = state.risk_assessment.risk_level if state.risk_assessment else "UNKNOWN"
        has_anomaly = state.anomaly_report.has_anomaly if state.anomaly_report else False
        # rule engine이 위험 판정했는데 perception이 이상 없다고 하거나 그 반대인 경우 충돌
        rule_non_safe = risk_level in ("CRITICAL", "WARNING")
        verdict_conflict = (rule_non_safe and not has_anomaly) or (risk_level == "SAFE" and has_anomaly)
        inp = RoutingInput(
            risk_level=risk_level,
            has_anomaly=has_anomaly,
            plan_step_count=len(state.action_plan.steps) if state.action_plan else 0,
            retry_count=state.retry_count,
            max_retries=s.pipeline_max_retries,
            recommendation=state.validation_result.recommendation if state.validation_result else None,
            verdict_conflict=verdict_conflict,
        )
        decision = apply_routing_rules(inp)

        _apply_routing_bridge(decision, state)

        decision_logger.append(DecisionEvent(
            correlation_id=state.correlation_id,
            stage="routing_gate",
            signals=inp.model_dump(),
            decision=decision.route,
            reason=f"[{decision.matched_rule}] {decision.reason}",
            duration_ms=(time.perf_counter() - _t0) * 1000,
        ))
        logger.info({
            "event": "pipeline_stage",
            "stage": "06_라우팅게이트(routing_gate)",
            "correlation_id": state.correlation_id,
            "route": decision.route,
            "matched_rule": decision.matched_rule,
            "reason": decision.reason,
        })

        lf = get_langfuse()
        if lf:
            obs = lf.start_observation(
                name="routing_gate",
                input=inp.model_dump(),
                output={"route": decision.route, "matched_rule": decision.matched_rule},
                metadata={"reason": decision.reason, "correlation_id": state.correlation_id},
            )
            obs.end()

        return {"routing_decision": decision, "stages_completed": state.stages_completed + ["routing_gate"]}

    # ── graph builder ──────────────────────────────────────────────────────────

    def _build_graph(self) -> Any:
        builder = StateGraph(_GraphState)

        builder.add_node("risk_assessment", self._node_risk_assessment)
        builder.add_node("perception", self._node_perception)
        builder.add_node("diagnostic_and_sop_rag", self._node_diagnostic_and_sop_rag)
        builder.add_node("action_plan", self._node_action_plan)
        builder.add_node("validator", self._node_validator)
        builder.add_node("routing_gate", self._node_routing)

        builder.add_edge(START, "risk_assessment")

        builder.add_conditional_edges(
            "risk_assessment",
            self._route_after_risk,
            {"early_exit": "routing_gate", "perception": "perception"},
        )
        builder.add_conditional_edges(
            "perception",
            self._route_after_perception,
            {"parallel": "diagnostic_and_sop_rag", "end_no_anomaly": "routing_gate"},
        )
        builder.add_edge("diagnostic_and_sop_rag", "action_plan")
        builder.add_edge("action_plan", "validator")
        builder.add_conditional_edges(
            "validator",
            self._route_after_validator,
            {
                "end_approved": "routing_gate",
                "retry_action_plan": "action_plan",
                "end_max_retries": "routing_gate",
            },
        )
        builder.add_edge("routing_gate", END)

        return builder.compile()

    # ── rule-only entry point ──────────────────────────────────────────────────

    async def run_rule_only(self, log: EquipmentLog, correlation_id: str) -> PipelineResult:
        """Ollama 불능 시 Rule Engine + ML predictor만 실행하는 폴백 경로."""
        logger.warning({
            "event": "pipeline_rule_only_mode",
            "correlation_id": correlation_id,
            "equipment_id": log.equipment_id,
            "reason": "ollama_unavailable",
        })

        state = _GraphState(log=log, correlation_id=correlation_id)
        state_updates = await self._node_risk_assessment(state)
        state = state.model_copy(update=state_updates)

        risk_level = state.risk_assessment.risk_level if state.risk_assessment else "UNKNOWN"
        inp = RoutingInput(
            risk_level=risk_level,
            has_anomaly=False,
            plan_step_count=0,
            retry_count=0,
            max_retries=get_settings().pipeline_max_retries,
            recommendation=None,
            verdict_conflict=False,
        )
        routing_decision = apply_routing_rules(inp)

        metrics = PipelineMetrics(
            risk_level=risk_level,
            early_exit=True,
            retry_count=0,
            stages_completed=state.stages_completed + ["routing_gate"],
            mode="rule-only",
        )

        logger.info({
            "event": "pipeline_complete",
            "correlation_id": correlation_id,
            "equipment_id": log.equipment_id,
            "risk_level": risk_level,
            "early_exit": True,
            "mode": "rule-only",
        })

        return PipelineResult(
            correlation_id=correlation_id,
            risk_assessment=state.risk_assessment,
            routing_decision=routing_decision,
            metrics=metrics,
        )

    # ── public entry point ─────────────────────────────────────────────────────

    async def run(self, log: EquipmentLog, correlation_id: str) -> PipelineResult:
        logger.info({
            "event": "pipeline_start",
            "correlation_id": correlation_id,
            "equipment_id": log.equipment_id,
        })

        lf = get_langfuse()

        async def _run_graph() -> PipelineResult:
            initial = _GraphState(log=log, correlation_id=correlation_id)
            raw: dict = await self._graph.ainvoke(initial)
            final = _GraphState.model_validate(raw)

            risk_level = final.risk_assessment.risk_level if final.risk_assessment else "UNKNOWN"
            early_exit = risk_level == "SAFE"
            retry_count = max(0, final.stages_completed.count("action_plan") - 1)

            metrics = PipelineMetrics(
                risk_level=risk_level,
                early_exit=early_exit,
                retry_count=retry_count,
                stages_completed=final.stages_completed,
            )

            logger.info({
                "event": "pipeline_complete",
                "correlation_id": correlation_id,
                "equipment_id": log.equipment_id,
                "risk_level": risk_level,
                "early_exit": early_exit,
                "has_anomaly": final.anomaly_report.has_anomaly if final.anomaly_report else None,
                "recommendation": final.validation_result.recommendation if final.validation_result else None,
                "retry_count": retry_count,
            })

            return PipelineResult(
                correlation_id=correlation_id,
                risk_assessment=final.risk_assessment,
                anomaly_report=final.anomaly_report,
                diagnostic_result=final.diagnostic_result,
                sop_context=final.sop_context,
                action_plan=final.action_plan,
                validation_result=final.validation_result,
                routing_decision=final.routing_decision,
                metrics=metrics,
            )

        if lf:
            with lf.start_as_current_observation(
                name="forge_pipeline",
                as_type="agent",
                input=log.model_dump(mode="json"),
                metadata={"equipment_id": log.equipment_id, "correlation_id": correlation_id},
            ) as _lf_root:
                result = await _run_graph()
                _lf_root.update(output={
                    "risk_level": result.metrics.risk_level,
                    "early_exit": result.metrics.early_exit,
                    "has_anomaly": result.anomaly_report.has_anomaly if result.anomaly_report else None,
                    "recommendation": result.validation_result.recommendation if result.validation_result else None,
                    "grounding_score": result.validation_result.overall_grounding_score if result.validation_result else None,
                })
            lf.flush()
        else:
            result = await _run_graph()

        return result
