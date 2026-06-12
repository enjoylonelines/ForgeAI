"""
End-to-End Pipeline Test
입력 → 분류(rule engine) → SOP 검색 → 행동계획 출력 전 단계를 5개 시나리오로 검증.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from models.equipment_log import EquipmentLog, SensorReading
from pipeline.forge_pipeline import ForgePipeline, PipelineResult

# ── pipeline_stage 이벤트만 골라서 터미널에 한 줄로 출력하는 핸들러 ──────────────

_STAGE_COLORS = {
    "01_분류(rule_engine)":    "\033[35m",  # magenta
    "02_이상탐지(perception)":  "\033[33m",  # yellow
    "03_SOP검색(sop_rag)":     "\033[32m",  # green
    "04_행동계획(action_plan)": "\033[31m",  # red
    "05_검증(validator)":      "\033[36m",  # cyan
}

class _StageHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            data = msg if isinstance(msg, dict) else json.loads(msg)
            if data.get("event") != "pipeline_stage":
                return
            stage = data.get("stage", "")
            color = _STAGE_COLORS.get(stage, "")
            reset = "\033[0m"
            bold  = "\033[1m"
            extras = {k: v for k, v in data.items() if k not in ("event", "stage", "correlation_id")}
            parts = ", ".join(f"{k}={v}" for k, v in extras.items())
            print(f"  {color}{bold}[{stage}]{reset} {parts}", flush=True)
        except Exception:
            pass

_stage_handler = _StageHandler()
logging.getLogger().addHandler(_stage_handler)

# ── ANSI 색상 ──────────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[36m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
MAGENTA= "\033[35m"
DIM    = "\033[2m"

# ── 테스트 케이스 정의 ─────────────────────────────────────────────────────────
ALL_CASES = [
    {
        "name": "TWF — 공구 마모 초과",
        "failure_type": "TWF",
        "log": EquipmentLog(
            equipment_id="M-TWF-001",
            timestamp=datetime(2026, 6, 11, 9, 0, 0, tzinfo=timezone.utc),
            log_level="ERROR",
            message="Tool wear exceeded threshold — possible tool failure",
            readings=[
                SensorReading(sensor_id="air_temperature_k",     unit="K",   value=298.0),
                SensorReading(sensor_id="process_temperature_k", unit="K",   value=308.0),
                SensorReading(sensor_id="rotational_speed_rpm",  unit="rpm", value=1500.0),
                SensorReading(sensor_id="torque_nm",             unit="Nm",  value=42.0),
                SensorReading(sensor_id="tool_wear_min",         unit="min", value=215.0),
            ],
        ),
    },
    {
        "name": "HDF — 열 방산 실패",
        "failure_type": "HDF",
        "log": EquipmentLog(
            equipment_id="M-HDF-002",
            timestamp=datetime(2026, 6, 11, 9, 5, 0, tzinfo=timezone.utc),
            log_level="WARN",
            message="Heat dissipation anomaly detected",
            readings=[
                SensorReading(sensor_id="air_temperature_k",     unit="K",   value=302.0),
                SensorReading(sensor_id="process_temperature_k", unit="K",   value=308.0),  # diff=6 < 8.6K
                SensorReading(sensor_id="rotational_speed_rpm",  unit="rpm", value=1200.0),  # < 1380
                SensorReading(sensor_id="torque_nm",             unit="Nm",  value=35.0),
                SensorReading(sensor_id="tool_wear_min",         unit="min", value=80.0),
            ],
        ),
    },
    {
        "name": "PWF — 전력 부족",
        "failure_type": "PWF",
        "log": EquipmentLog(
            equipment_id="M-PWF-003",
            timestamp=datetime(2026, 6, 11, 9, 10, 0, tzinfo=timezone.utc),
            log_level="ERROR",
            message="Power output below minimum operational threshold",
            readings=[
                SensorReading(sensor_id="air_temperature_k",     unit="K",   value=299.0),
                SensorReading(sensor_id="process_temperature_k", unit="K",   value=309.0),
                SensorReading(sensor_id="rotational_speed_rpm",  unit="rpm", value=1400.0),
                SensorReading(sensor_id="torque_nm",             unit="Nm",  value=15.0),  # power=15*1400*2π/60≈2199W < 3500
                SensorReading(sensor_id="tool_wear_min",         unit="min", value=90.0),
            ],
        ),
    },
    {
        "name": "OSF — 과부하 변형",
        "failure_type": "OSF",
        "log": EquipmentLog(
            equipment_id="M-OSF-004",
            timestamp=datetime(2026, 6, 11, 9, 15, 0, tzinfo=timezone.utc),
            log_level="WARN",
            message="Overstrain condition: tool wear × torque exceeds limit",
            readings=[
                SensorReading(sensor_id="air_temperature_k",     unit="K",   value=300.0),
                SensorReading(sensor_id="process_temperature_k", unit="K",   value=310.0),
                SensorReading(sensor_id="rotational_speed_rpm",  unit="rpm", value=1000.0),
                SensorReading(sensor_id="torque_nm",             unit="Nm",  value=60.0),
                SensorReading(sensor_id="tool_wear_min",         unit="min", value=190.0),  # 190*60=11400 > 11000, power=6283W(정상범위)
            ],
        ),
    },
    {
        "name": "SAFE — 정상 운전 (early exit)",
        "failure_type": "NONE",
        "log": EquipmentLog(
            equipment_id="M-SAFE-005",
            timestamp=datetime(2026, 6, 11, 9, 20, 0, tzinfo=timezone.utc),
            log_level="INFO",
            message="Normal operation",
            readings=[
                SensorReading(sensor_id="air_temperature_k",     unit="K",   value=300.0),
                SensorReading(sensor_id="process_temperature_k", unit="K",   value=309.0),
                SensorReading(sensor_id="rotational_speed_rpm",  unit="rpm", value=2000.0),
                SensorReading(sensor_id="torque_nm",             unit="Nm",  value=40.0),
                SensorReading(sensor_id="tool_wear_min",         unit="min", value=100.0),
            ],
        ),
    },
]

CASES = ALL_CASES  # 5개 전체


# ── 출력 헬퍼 ──────────────────────────────────────────────────────────────────

def _sep(char: str = "─", width: int = 72) -> str:
    return char * width


def _header(text: str) -> None:
    print(f"\n{BOLD}{CYAN}{_sep('═')}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{_sep('═')}{RESET}")


def _section(label: str, color: str = YELLOW) -> None:
    print(f"\n{color}{BOLD}▶ {label}{RESET}")
    print(f"{DIM}{_sep()}{RESET}")


def _kv(key: str, value: object, color: str = RESET) -> None:
    print(f"  {DIM}{key:<28}{RESET}{color}{value}{RESET}")


def _print_input(case: dict) -> None:
    _section("① 입력 (EquipmentLog)", CYAN)
    log: EquipmentLog = case["log"]
    _kv("equipment_id",   log.equipment_id)
    _kv("timestamp",      log.timestamp.isoformat())
    _kv("log_level",      log.log_level)
    _kv("message",        log.message)
    print(f"  {DIM}{'readings':<28}{RESET}")
    for r in log.readings:
        print(f"    {r.sensor_id:<32} {r.value:>10.1f} {r.unit}")


def _print_classification(result: PipelineResult) -> None:
    _section("② 분류 (Rule Engine)", MAGENTA)
    ra = result.risk_assessment
    if not ra:
        _kv("risk_level", "N/A")
        return
    level_color = RED if ra.risk_level == "CRITICAL" else YELLOW if ra.risk_level in ("WARNING", "HIGH") else GREEN
    _kv("risk_level",    ra.risk_level,    level_color)
    _kv("failure_type",  ra.failure_type,  MAGENTA)
    _kv("summary",       ra.summary)
    if ra.risk_factors:
        print(f"  {DIM}risk_factors:{RESET}")
        for rf in ra.risk_factors:
            print(f"    • {rf.sensor_id}: {rf.current_value:.1f}  utilization={rf.utilization_pct:.1f}%")
            print(f"      {DIM}{rf.description}{RESET}")


def _print_anomaly(result: PipelineResult) -> None:
    _section("③ 이상 감지 (PerceptionAgent)", YELLOW)
    ar = result.anomaly_report
    if not ar:
        print(f"  {DIM}(실행되지 않음 — early exit){RESET}")
        return
    _kv("has_anomaly", ar.has_anomaly, RED if ar.has_anomaly else GREEN)
    _kv("summary",     ar.summary)
    if ar.anomalies:
        print(f"  {DIM}anomalies:{RESET}")
        for a in ar.anomalies:
            print(f"    • [{a.severity}] {a.sensor_id}: {a.observed_value}  {a.description}")


def _print_sop(result: PipelineResult) -> None:
    _section("④ SOP 검색 (SOPRAGAgent)", GREEN)
    sc = result.sop_context
    if not sc:
        print(f"  {DIM}(실행되지 않음 — early exit){RESET}")
        return
    _kv("query_used",  sc.query_used)
    _kv("chunk_count", len(sc.chunks))
    if sc.chunks:
        print(f"  {DIM}top chunks:{RESET}")
        for ch in sc.chunks[:3]:
            score_str = f"  score={ch.relevance_score:.3f}" if ch.relevance_score is not None else ""
            print(f"    • {ch.chunk_id}{score_str}")
            snippet = ch.text[:120].replace("\n", " ")
            print(f"      {DIM}{snippet}…{RESET}")


def _print_action_plan(result: PipelineResult) -> None:
    _section("⑤ 행동 계획 (ActionPlanAgent)", RED)
    ap = result.action_plan
    if not ap:
        print(f"  {DIM}(실행되지 않음 — early exit){RESET}")
        return
    _kv("escalation_required", ap.escalation_required, RED if ap.escalation_required else GREEN)
    if ap.escalation_reason:
        _kv("escalation_reason", ap.escalation_reason)
    print(f"  {DIM}steps:{RESET}")
    for s in ap.steps:
        print(f"    [{s.step_number}] {BOLD}{s.action}{RESET}")
        print(f"        role={s.responsible_role}  priority={s.priority}  ~{s.estimated_duration_minutes}min")
        if s.sop_reference:
            print(f"        {DIM}SOP: {s.sop_reference}{RESET}")


def _print_validation(result: PipelineResult) -> None:
    _section("⑥ 검증 (HallucinationValidator)", CYAN)
    vr = result.validation_result
    if not vr:
        print(f"  {DIM}(실행되지 않음 — early exit){RESET}")
        return
    rec_color = GREEN if vr.recommendation == "APPROVE" else YELLOW if vr.recommendation == "REVIEW" else RED
    _kv("recommendation",     vr.recommendation, rec_color)
    _kv("grounding_score",    f"{vr.overall_grounding_score:.3f}")
    _kv("explanation",        vr.explanation or "—")
    if vr.ungrounded_steps:
        _kv("ungrounded_steps", vr.ungrounded_steps, RED)


def _print_metrics(result: PipelineResult, elapsed: float) -> None:
    _section("⑦ 메트릭", DIM)
    m = result.metrics
    _kv("stages_completed", " → ".join(m.stages_completed) or "(risk_assessment only)")
    _kv("retry_count",      m.retry_count)
    _kv("early_exit",       m.early_exit, YELLOW if m.early_exit else RESET)
    _kv("elapsed_sec",      f"{elapsed:.1f}s")


# ── 실행 ───────────────────────────────────────────────────────────────────────

async def run_all() -> None:
    pipeline = ForgePipeline()
    total_start = time.perf_counter()
    summaries: list[dict] = []

    for i, case in enumerate(CASES, 1):
        cid = f"e2e-{case['log'].equipment_id}-{i:02d}"
        _header(f"케이스 {i}/5 | {case['name']}  ({cid})")

        _print_input(case)

        t0 = time.perf_counter()
        result = await pipeline.run(case["log"], cid)
        elapsed = time.perf_counter() - t0

        _print_classification(result)
        _print_anomaly(result)
        _print_sop(result)
        _print_action_plan(result)
        _print_validation(result)
        _print_metrics(result, elapsed)

        rec = result.validation_result.recommendation if result.validation_result else "EARLY_EXIT"
        summaries.append({
            "case":         case["name"],
            "expected_ft":  case["failure_type"],
            "actual_ft":    result.risk_assessment.failure_type if result.risk_assessment else "N/A",
            "risk_level":   result.risk_assessment.risk_level   if result.risk_assessment else "N/A",
            "has_anomaly":  result.anomaly_report.has_anomaly   if result.anomaly_report  else None,
            "sop_chunks":   len(result.sop_context.chunks)      if result.sop_context     else 0,
            "plan_steps":   len(result.action_plan.steps)       if result.action_plan     else 0,
            "validation":   rec,
            "elapsed_sec":  round(elapsed, 1),
        })

    total_elapsed = time.perf_counter() - total_start

    # ── 최종 요약표 ─────────────────────────────────────────────────────────────
    print(f"\n\n{BOLD}{CYAN}{_sep('═')}{RESET}")
    print(f"{BOLD}{CYAN}  최종 요약{RESET}")
    print(f"{BOLD}{CYAN}{_sep('═')}{RESET}")

    col_w = [28, 8, 8, 10, 10, 6, 6, 10, 8]
    headers = ["케이스", "예상FT", "실제FT", "위험수준", "이상감지", "SOP청크", "스텝수", "검증결과", "시간(s)"]
    header_row = "  " + "  ".join(h.ljust(col_w[j]) for j, h in enumerate(headers))
    print(f"\n{BOLD}{header_row}{RESET}")
    print(f"  {_sep('-', 96)}")

    for s in summaries:
        ft_match = s["expected_ft"] == s["actual_ft"]
        ft_color = GREEN if ft_match else RED
        rec_color = GREEN if s["validation"] == "APPROVE" else YELLOW if s["validation"] in ("REVIEW", "EARLY_EXIT") else RED
        row_vals = [
            s["case"][:28],
            s["expected_ft"],
            s["actual_ft"],
            s["risk_level"],
            str(s["has_anomaly"]),
            str(s["sop_chunks"]),
            str(s["plan_steps"]),
            s["validation"],
            str(s["elapsed_sec"]),
        ]
        row = "  " + "  ".join(v.ljust(col_w[j]) for j, v in enumerate(row_vals))
        print(row)

    print(f"\n  총 소요 시간: {BOLD}{total_elapsed:.1f}초{RESET}\n")


if __name__ == "__main__":
    asyncio.run(run_all())
