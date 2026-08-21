from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from agents.base import MaxRetriesExceededError, ParseOutputError
from control.bridge import ControlAdapterError, execute_control_plan
from core.config import get_settings
from core.logging import get_logger
from core.ollama_client import health_check as ollama_health
from models.equipment_log import EquipmentLog
from models.control_command import ControlPlanRequest, ControlPlanResult
from models.user_query import NLDiagnosisResult, UserQueryRequest
from pipeline.forge_pipeline import ForgePipeline, PipelineResult
from pipeline.nl_diagnosis_pipeline import NLDiagnosisPipeline
from rag.chroma_client import get_sop_collection, health_check as chroma_health
from rag.ingestion import IngestResult, ingest_document
from utils.csv_parser import parse_csv_logs

logger = get_logger(__name__)
router = APIRouter()


class CSVAnalyzeResult(BaseModel):
    total_rows: int
    processed_rows: int
    anomaly_count: int
    results: list[dict]
    improvement_metrics: dict = {}


async def _llm_provider_status() -> tuple[str, bool, str]:
    """Return provider, readiness, and Ollama status for the configured mode."""
    settings = get_settings()
    if settings.llm_mode == "api":
        return "api", bool(settings.llm_api_key), "not_required"

    ollama_ok = await ollama_health()
    return "ollama", ollama_ok, "ok" if ollama_ok else "error"


@router.post("/analyze")
async def analyze(request: Request, log: EquipmentLog) -> Response:
    correlation_id = request.headers.get("X-Correlation-ID") or uuid.uuid4().hex
    _, llm_ok, _ = await _llm_provider_status()
    pipeline = ForgePipeline()
    try:
        if llm_ok:
            result = await pipeline.run(log, correlation_id)
        else:
            result = await pipeline.run_rule_only(log, correlation_id)
    except MaxRetriesExceededError:
        # LLM이 중간에 사망한 경우에도 rule-only 폴백
        result = await pipeline.run_rule_only(log, correlation_id)
    except ParseOutputError as exc:
        raise HTTPException(status_code=422, detail={"error": "parse_error", "message": str(exc), "correlation_id": correlation_id})

    headers: dict[str, str] = {"X-Mode": result.metrics.mode}
    rec = result.validation_result.recommendation if result.validation_result else None
    if rec == "REJECT":
        headers["X-Plan-Status"] = "REJECTED"
    elif rec == "REVIEW":
        headers["X-Plan-Status"] = "REVIEW"
    if result.routing_decision:
        headers["X-Route"] = result.routing_decision.route
        headers["X-Matched-Rule"] = result.routing_decision.matched_rule

    return Response(
        content=result.model_dump_json(),
        media_type="application/json",
        headers=headers,
    )


@router.post("/analyze/csv", response_model=CSVAnalyzeResult)
async def analyze_csv(request: Request, file: UploadFile) -> CSVAnalyzeResult:
    correlation_prefix = request.headers.get("X-Correlation-ID") or uuid.uuid4().hex
    file_bytes = await file.read()
    logs = parse_csv_logs(file_bytes, filename=file.filename or "")

    pipeline = ForgePipeline()
    results = []
    anomaly_count = 0

    early_exit_count = 0
    warning_count = 0
    retry_total = 0

    for i, log in enumerate(logs):
        cid = f"{correlation_prefix}-row{i}"
        try:
            result = await pipeline.run(log, cid)
            m = result.metrics
            if result.anomaly_report and result.anomaly_report.has_anomaly:
                anomaly_count += 1
            if m.early_exit:
                early_exit_count += 1
            if m.risk_level == "WARNING":
                warning_count += 1
            retry_total += m.retry_count
            results.append({
                "row_index": i,
                "correlation_id": cid,
                "equipment_id": log.equipment_id,
                "risk_level": m.risk_level,
                "early_exit": m.early_exit,
                "retry_count": m.retry_count,
                "has_anomaly": result.anomaly_report.has_anomaly if result.anomaly_report else None,
                "recommendation": result.validation_result.recommendation if result.validation_result else None,
                "grounding_score": result.validation_result.overall_grounding_score if result.validation_result else None,
                "summary": result.anomaly_report.summary if result.anomaly_report else None,
            })
        except Exception as exc:
            logger.warning({"event": "csv_row_failed", "row_index": i, "error": str(exc)})
            results.append({"row_index": i, "correlation_id": cid, "error": str(exc)})

    processed = len([r for r in results if "error" not in r])
    improvement_metrics = {
        "early_exit_count": early_exit_count,
        "early_exit_rate_pct": round(early_exit_count / processed * 100, 1) if processed else 0.0,
        "warning_prevented_count": warning_count,
        "warning_rate_pct": round(warning_count / processed * 100, 1) if processed else 0.0,
        "avg_retries_per_row": round(retry_total / processed, 2) if processed else 0.0,
        "llm_calls_saved": early_exit_count * 4,
    }

    return CSVAnalyzeResult(
        total_rows=len(logs),
        processed_rows=processed,
        anomaly_count=anomaly_count,
        results=results,
        improvement_metrics=improvement_metrics,
    )


@router.post("/diagnose", response_model=NLDiagnosisResult)
async def diagnose(request: Request, body: UserQueryRequest) -> NLDiagnosisResult:
    correlation_id = request.headers.get("X-Correlation-ID") or uuid.uuid4().hex
    try:
        pipeline = NLDiagnosisPipeline()
        return await pipeline.run(body, correlation_id)
    except MaxRetriesExceededError as exc:
        raise HTTPException(status_code=503, detail={"error": "llm_unavailable", "message": str(exc), "correlation_id": correlation_id})
    except ParseOutputError as exc:
        raise HTTPException(status_code=422, detail={"error": "parse_error", "message": str(exc), "correlation_id": correlation_id})


@router.post("/control/plan", response_model=ControlPlanResult)
async def control_plan(request: Request, body: ControlPlanRequest) -> ControlPlanResult:
    correlation_id = request.headers.get("X-Correlation-ID") or uuid.uuid4().hex
    try:
        return execute_control_plan(body.action_plan, correlation_id, dry_run=body.dry_run)
    except ControlAdapterError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "control_adapter_unavailable", "message": str(exc), "correlation_id": correlation_id},
        )


@router.post("/ingest", response_model=IngestResult)
async def ingest(
    file: UploadFile,
    equipment_tags: str = "",
) -> IngestResult:
    content_type = file.content_type or ""
    filename = file.filename or "document"

    if not (
        content_type in ("application/pdf", "text/markdown", "text/plain")
        or filename.lower().endswith((".pdf", ".md", ".txt"))
    ):
        raise HTTPException(status_code=415, detail="Unsupported file type. Use PDF or Markdown.")

    file_bytes = await file.read()
    tags = [t.strip() for t in equipment_tags.split(",") if t.strip()]

    try:
        return await ingest_document(
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            equipment_tags=tags,
        )
    except Exception as exc:
        logger.warning({"event": "ingest_failed", "file": filename, "error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/health")
async def health() -> JSONResponse:
    llm_provider, llm_ok, ollama_status = await _llm_provider_status()
    chroma_ok = chroma_health()

    try:
        doc_count = get_sop_collection().count()
    except Exception:
        doc_count = -1

    if llm_ok and chroma_ok:
        status, http_code = "ok", 200
    elif not chroma_ok:
        # ChromaDB 없이는 SOP 검색·임베딩 불가 — 근본적 장애
        status, http_code = "error", 503
    else:
        # Configured LLM provider unavailable → rule-only mode remains ready.
        status, http_code = "degraded", 200

    mode = "full" if llm_ok else "rule-only"
    return JSONResponse(
        content={
            "status": status,
            "mode": mode,
            "llm_provider": llm_provider,
            "llm": "ok" if llm_ok else "error",
            "ollama": ollama_status,
            "chromadb": "ok" if chroma_ok else "error",
            "collection_doc_count": doc_count,
        },
        status_code=http_code,
    )
