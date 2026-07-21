"""
이슈 #30: 판단 충돌 → 에스컬레이션 케이스 재현 스크립트

목적: D5 정책(충돌=불확실성 증거)의 작동을 검증한다.
  - rule_engine(결정론적) vs perception(LLM) 불일치를 합성 케이스로 재현
  - verdict_conflict=True → R-C1(ESCALATE) / R-C2(HUMAN_REVIEW) 라우팅 확인
  - Langfuse 트레이스 캡처

충돌 조건:
  rule_non_safe = risk_level in (CRITICAL, WARNING)
  verdict_conflict = (rule_non_safe AND NOT has_anomaly)
                   OR (risk_level == SAFE AND has_anomaly)
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

# Langfuse 활성화 — 환경 변수 로드 전에 설정해야 lru_cache에 반영됨
os.environ.setdefault("LANGFUSE_ENABLED", "true")

from models.anomaly_report import AnomalyReport
from models.equipment_log import EquipmentLog, SensorReading
from pipeline.forge_pipeline import ForgePipeline, PipelineResult

# ── ANSI ──────────────────────────────────────────────────────────────────────
RESET   = "\033[0m"
BOLD    = "\033[1m"
CYAN    = "\033[36m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
RED     = "\033[31m"
MAGENTA = "\033[35m"
DIM     = "\033[2m"


def _sep(char: str = "─", width: int = 72) -> str:
    return char * width


def _header(text: str) -> None:
    print(f"\n{BOLD}{CYAN}{_sep('═')}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{_sep('═')}{RESET}")


def _kv(key: str, value: object, color: str = RESET) -> None:
    print(f"  {DIM}{key:<30}{RESET}{color}{value}{RESET}")


# ── 합성 충돌 케이스 정의 ─────────────────────────────────────────────────────

# Case 1 — WARNING + conflict → R-C2 → HUMAN_REVIEW
#   rule_engine: tool_wear_min=215 ≥ 200 → TWF → WARNING
#   perception(mock): has_anomaly=False  (LLM이 일상 점검 메시지를 보고 이상 없다고 판단하는 시뮬레이션)
CASE_WARNING = {
    "name": "WARNING 충돌 (R-C2 → HUMAN_REVIEW)",
    "description": (
        "tool_wear=215min → rule_engine=WARNING(TWF), "
        "하지만 perception=has_anomaly=False. "
        "충돌 감지 → R-C2 → HUMAN_REVIEW."
    ),
    "expected_rule": "R-C2",
    "expected_route": "HUMAN_REVIEW",
    "log": EquipmentLog(
        equipment_id="M-CONFLICT-W01",
        timestamp=datetime(2026, 7, 20, 9, 0, 0, tzinfo=timezone.utc),
        log_level="INFO",
        message="Routine daily maintenance check — no issues observed by operator",
        readings=[
            SensorReading(sensor_id="air_temperature_k",     unit="K",   value=299.0),
            SensorReading(sensor_id="process_temperature_k", unit="K",   value=309.0),
            SensorReading(sensor_id="rotational_speed_rpm",  unit="rpm", value=1500.0),
            SensorReading(sensor_id="torque_nm",             unit="Nm",  value=42.0),
            # tool_wear_min=215: 범위 0~250, util=86% → WARNING; ≥200 → TWF
            SensorReading(sensor_id="tool_wear_min",         unit="min", value=215.0),
        ],
    ),
    "mock_perception": AnomalyReport(
        equipment_id="M-CONFLICT-W01",
        timestamp=datetime(2026, 7, 20, 9, 0, 0, tzinfo=timezone.utc),
        has_anomaly=False,
        anomalies=[],
        summary="No anomaly detected. Sensor values appear within normal range for a routine check.",
        raw_log_snippet="Routine daily maintenance check — no issues observed by operator",
        correlation_id=None,
    ),
}

# Case 2 — CRITICAL + conflict → R-C1 → ESCALATE
#   rule_engine: tool_wear_min=240 → util=96% → CRITICAL; ≥200 → TWF
#   perception(mock): has_anomaly=False
CASE_CRITICAL = {
    "name": "CRITICAL 충돌 (R-C1 → ESCALATE)",
    "description": (
        "tool_wear=240min → rule_engine=CRITICAL(TWF), "
        "하지만 perception=has_anomaly=False. "
        "충돌 감지 → R-C1 → ESCALATE."
    ),
    "expected_rule": "R-C1",
    "expected_route": "ESCALATE",
    "log": EquipmentLog(
        equipment_id="M-CONFLICT-C01",
        timestamp=datetime(2026, 7, 20, 9, 5, 0, tzinfo=timezone.utc),
        log_level="INFO",
        message="Standard shift handover log — machine running smoothly per operator report",
        readings=[
            SensorReading(sensor_id="air_temperature_k",     unit="K",   value=299.0),
            SensorReading(sensor_id="process_temperature_k", unit="K",   value=309.0),
            SensorReading(sensor_id="rotational_speed_rpm",  unit="rpm", value=1500.0),
            SensorReading(sensor_id="torque_nm",             unit="Nm",  value=42.0),
            # tool_wear_min=240: util=(240-0)/(250-0)*100=96% ≥ 95% → CRITICAL
            SensorReading(sensor_id="tool_wear_min",         unit="min", value=240.0),
        ],
    ),
    "mock_perception": AnomalyReport(
        equipment_id="M-CONFLICT-C01",
        timestamp=datetime(2026, 7, 20, 9, 5, 0, tzinfo=timezone.utc),
        has_anomaly=False,
        anomalies=[],
        summary="Operator report indicates normal operation. No anomaly detected from message context.",
        raw_log_snippet="Standard shift handover log — machine running smoothly per operator report",
        correlation_id=None,
    ),
}

CASES = [CASE_WARNING, CASE_CRITICAL]


# ── 실행 ──────────────────────────────────────────────────────────────────────

async def run_conflict_case(pipeline: ForgePipeline, case: dict, idx: int) -> dict:
    log: EquipmentLog = case["log"]
    cid = f"conflict-{log.equipment_id}-{idx:02d}"
    mock_report: AnomalyReport = case["mock_perception"]
    mock_report = mock_report.model_copy(update={"correlation_id": cid})

    _header(f"케이스 {idx} | {case['name']}  ({cid})")
    print(f"\n  {DIM}[합성 케이스] perception 에이전트는 mock으로 대체됩니다.{RESET}")
    print(f"  {DIM}{case['description']}{RESET}")

    print(f"\n{YELLOW}{BOLD}▶ 입력{RESET}")
    _kv("equipment_id", log.equipment_id)
    _kv("log_message",  log.message)
    for r in log.readings:
        _kv(f"  {r.sensor_id}", f"{r.value:.1f} {r.unit}")

    print(f"\n{YELLOW}{BOLD}▶ Mock Perception 응답{RESET}")
    _kv("has_anomaly", mock_report.has_anomaly, GREEN if not mock_report.has_anomaly else RED)
    _kv("summary",     mock_report.summary)

    with patch.object(pipeline._perception, "run", new=AsyncMock(return_value=mock_report)):
        result: PipelineResult = await pipeline.run(log, cid)

    ra = result.risk_assessment
    rd = result.routing_decision

    print(f"\n{MAGENTA}{BOLD}▶ Rule Engine 결과{RESET}")
    risk_color = RED if ra and ra.risk_level == "CRITICAL" else YELLOW if ra and ra.risk_level == "WARNING" else GREEN
    _kv("risk_level",   ra.risk_level   if ra else "N/A", risk_color)
    _kv("failure_type", ra.failure_type if ra else "N/A", MAGENTA)
    if ra and ra.risk_factors:
        for rf in ra.risk_factors:
            _kv(f"  {rf.sensor_id}", f"util={rf.utilization_pct:.1f}%  value={rf.current_value:.1f}")

    print(f"\n{CYAN}{BOLD}▶ 라우팅 결과 (충돌 감지){RESET}")
    route_color = RED if rd and rd.route == "ESCALATE" else YELLOW if rd and rd.route == "HUMAN_REVIEW" else GREEN
    _kv("verdict_conflict", True, RED)
    _kv("route",        rd.route        if rd else "N/A", route_color)
    _kv("matched_rule", rd.matched_rule if rd else "N/A", BOLD)
    _kv("reason",       rd.reason       if rd else "N/A")

    expected_rule  = case["expected_rule"]
    expected_route = case["expected_route"]
    rule_ok  = rd and rd.matched_rule == expected_rule
    route_ok = rd and rd.route        == expected_route
    status = f"{GREEN}PASS{RESET}" if (rule_ok and route_ok) else f"{RED}FAIL{RESET}"
    print(f"\n  검증: rule={expected_rule}({GREEN+'OK'+RESET if rule_ok else RED+'NG'+RESET})  "
          f"route={expected_route}({GREEN+'OK'+RESET if route_ok else RED+'NG'+RESET})  → {status}")

    return {
        "correlation_id":    cid,
        "name":              case["name"],
        "equipment_id":      log.equipment_id,
        "risk_level":        ra.risk_level        if ra else "N/A",
        "failure_type":      ra.failure_type       if ra else "N/A",
        "mock_has_anomaly":  mock_report.has_anomaly,
        "verdict_conflict":  True,
        "route":             rd.route              if rd else "N/A",
        "matched_rule":      rd.matched_rule       if rd else "N/A",
        "reason":            rd.reason             if rd else "N/A",
        "pass":              bool(rule_ok and route_ok),
        "langfuse_trace_id": cid,
        "input_log": {
            "equipment_id": log.equipment_id,
            "timestamp":    log.timestamp.isoformat(),
            "log_level":    log.log_level,
            "message":      log.message,
            "readings":     [
                {"sensor_id": r.sensor_id, "value": r.value, "unit": r.unit}
                for r in log.readings
            ],
        },
    }


async def main() -> None:
    pipeline = ForgePipeline()
    results = []

    for i, case in enumerate(CASES, 1):
        r = await run_conflict_case(pipeline, case, i)
        results.append(r)

    # ── 요약 ───────────────────────────────────────────────────────────────────
    print(f"\n\n{BOLD}{CYAN}{_sep('═')}{RESET}")
    print(f"{BOLD}{CYAN}  충돌 케이스 요약{RESET}")
    print(f"{BOLD}{CYAN}{_sep('═')}{RESET}\n")
    all_pass = all(r["pass"] for r in results)
    for r in results:
        status = f"{GREEN}PASS{RESET}" if r["pass"] else f"{RED}FAIL{RESET}"
        print(f"  {status}  {r['name']}")
        print(f"       risk={r['risk_level']}  conflict=True → {BOLD}{r['route']}{RESET} ({r['matched_rule']})")
        print(f"       Langfuse trace_id: {DIM}{r['langfuse_trace_id']}{RESET}")

    print(f"\n  전체: {'전부 통과' if all_pass else '일부 실패'}")

    # ── 충돌 케이스 JSON 파일 저장 ────────────────────────────────────────────
    output_path = "data/conflict_case_synthetic.json"
    payload = {
        "generated_at":  datetime.now(timezone.utc).isoformat(),
        "description":   "이슈 #30 합성 충돌 케이스 — D5 정책(충돌=불확실성 증거) 작동 검증",
        "policy":        "verdict_conflict=(rule_non_safe AND NOT has_anomaly): R-C1(CRITICAL→ESCALATE), R-C2(WARNING→HUMAN_REVIEW)",
        "cases": results,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n  충돌 케이스 파일 저장: {BOLD}{output_path}{RESET}")
    print(f"\n  Langfuse 트레이스 확인: {DIM}https://jp.cloud.langfuse.com{RESET}")
    print(f"  (trace_id 기준으로 검색: {', '.join(r['langfuse_trace_id'] for r in results)})\n")


if __name__ == "__main__":
    asyncio.run(main())
