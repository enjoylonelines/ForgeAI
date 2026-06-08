from __future__ import annotations

import asyncio
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
from core.langfuse_client import get_langfuse, set_current_trace
from core.logging import get_logger
from core.rule_engine import assess_risk
from models.action_plan import ActionPlan
from models.anomaly_report import AnomalyReport
from models.diagnostic_result import DiagnosticResult
from models.equipment_log import EquipmentLog
from models.risk_assessment import RiskAssessment
from models.sop_context import SOPContext
from models.validation_result import ValidationResult

logger = get_logger(__name__)


class PipelineMetrics(BaseModel):
    risk_level: str = "UNKNOWN"
    early_exit: bool = False
    retry_count: int = 0
    stages_completed: list[str] = []


class PipelineResult(BaseModel):
    correlation_id: str
    risk_assessment: RiskAssessment | None = None
    anomaly_report: AnomalyReport | None = None
    diagnostic_result: DiagnosticResult | None = None
    sop_context: SOPContext | None = None
    action_plan: ActionPlan | None = None
    validation_result: ValidationResult | None = None
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
        assessment = assess_risk(state.log, state.correlation_id)
        logger.info({
            "event": "risk_assessment_complete",
            "correlation_id": state.correlation_id,
            "equipment_id": state.log.equipment_id,
            "risk_level": assessment.risk_level,
            "risk_factor_count": len(assessment.risk_factors),
        })
        return {
            "risk_assessment": assessment,
            "stages_completed": state.stages_completed + ["risk_assessment"],
        }

    async def _node_perception(self, state: _GraphState) -> dict[str, Any]:
        report = await self._perception.run(state.log, state.correlation_id)
        return {
            "anomaly_report": report,
            "stages_completed": state.stages_completed + ["perception"],
        }

    async def _node_diagnostic_and_sop_rag(self, state: _GraphState) -> dict[str, Any]:
        """Run diagnostic and SOP-RAG in parallel — both only need anomaly_report."""
        diagnostic_result, sop_ctx = await asyncio.gather(
            self._diagnostic.run(state.anomaly_report, state.correlation_id),
            self._sop_rag.run(state.anomaly_report, state.correlation_id),
        )
        return {
            "diagnostic_result": diagnostic_result,
            "sop_context": sop_ctx,
            "stages_completed": state.stages_completed + ["diagnostic", "sop_rag"],
        }

    async def _node_action_plan(self, state: _GraphState) -> dict[str, Any]:
        plan = await self._action_plan.run(
            state.anomaly_report,
            state.sop_context,
            state.correlation_id,
            previous_feedback=state.previous_feedback,
            retry_attempt=state.retry_count,
        )
        return {
            "action_plan": plan,
            "stages_completed": state.stages_completed + ["action_plan"],
        }

    async def _node_validator(self, state: _GraphState) -> dict[str, Any]:
        result = await self._validator.run(state.action_plan, state.sop_context, state.correlation_id)
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

    @staticmethod
    def _route_after_risk(state: _GraphState) -> str:
        if state.risk_assessment and state.risk_assessment.risk_level == "SAFE":
            return "early_exit"
        return "perception"

    @staticmethod
    def _route_after_perception(state: _GraphState) -> str:
        if state.anomaly_report and state.anomaly_report.has_anomaly:
            return "parallel"
        return "end_no_anomaly"

    @staticmethod
    def _route_after_validator(state: _GraphState) -> str:
        rec = state.validation_result.recommendation if state.validation_result else "APPROVE"
        if rec in ("APPROVE", "REVIEW"):
            return "end_approved"
        max_retries = get_settings().pipeline_max_retries
        if state.retry_count < max_retries:
            return "retry_action_plan"
        return "end_max_retries"

    # ── graph builder ──────────────────────────────────────────────────────────

    def _build_graph(self) -> Any:
        builder = StateGraph(_GraphState)

        builder.add_node("risk_assessment", self._node_risk_assessment)
        builder.add_node("perception", self._node_perception)
        builder.add_node("diagnostic_and_sop_rag", self._node_diagnostic_and_sop_rag)
        builder.add_node("action_plan", self._node_action_plan)
        builder.add_node("validator", self._node_validator)

        builder.add_edge(START, "risk_assessment")

        builder.add_conditional_edges(
            "risk_assessment",
            self._route_after_risk,
            {"early_exit": END, "perception": "perception"},
        )
        builder.add_conditional_edges(
            "perception",
            self._route_after_perception,
            {"parallel": "diagnostic_and_sop_rag", "end_no_anomaly": END},
        )
        builder.add_edge("diagnostic_and_sop_rag", "action_plan")
        builder.add_edge("action_plan", "validator")
        builder.add_conditional_edges(
            "validator",
            self._route_after_validator,
            {
                "end_approved": END,
                "retry_action_plan": "action_plan",
                "end_max_retries": END,
            },
        )

        return builder.compile()

    # ── public entry point ─────────────────────────────────────────────────────

    async def run(self, log: EquipmentLog, correlation_id: str) -> PipelineResult:
        logger.info({
            "event": "pipeline_start",
            "correlation_id": correlation_id,
            "equipment_id": log.equipment_id,
        })

        lf = get_langfuse()
        trace = None
        if lf:
            trace = lf.trace(
                id=correlation_id,
                name="forge_pipeline",
                input=log.model_dump(mode="json"),
                metadata={"equipment_id": log.equipment_id},
            )
            set_current_trace(trace)

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

        if trace:
            trace.update(output={
                "risk_level": risk_level,
                "early_exit": early_exit,
                "has_anomaly": final.anomaly_report.has_anomaly if final.anomaly_report else None,
                "recommendation": final.validation_result.recommendation if final.validation_result else None,
                "grounding_score": final.validation_result.overall_grounding_score if final.validation_result else None,
            })
            lf.flush()

        return PipelineResult(
            correlation_id=correlation_id,
            risk_assessment=final.risk_assessment,
            anomaly_report=final.anomaly_report,
            diagnostic_result=final.diagnostic_result,
            sop_context=final.sop_context,
            action_plan=final.action_plan,
            validation_result=final.validation_result,
            metrics=metrics,
        )
