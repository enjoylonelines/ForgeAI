#!/usr/bin/env python3
"""
에스컬레이션 경계 작동 데모 (이슈 #28).

자동 처리(AUTO) 1건 + 사람 확인(ESCALATE) 1건의 실행 예시를 터미널에 출력한다.

사용법:
    uv run python scripts/escalation_demo.py
"""
from __future__ import annotations

import asyncio
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.equipment_log import EquipmentLog, SensorReading
from pipeline.forge_pipeline import ForgePipeline, PipelineResult

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
MAGENTA= "\033[35m"
DIM    = "\033[2m"

# ── 데모 케이스 ────────────────────────────────────────────────────────────────

DEMO_CASES = [
    {
        "label": "CASE A — 정상 운전 (자동 처리 예상)",
        "expected_route": "AUTO",
        "log": EquipmentLog(
            equipment_id="DEMO-AUTO-001",
            timestamp=datetime(2026, 7, 15, 9, 0, 0, tzinfo=timezone.utc),
            log_level="INFO",
            message="Normal operation — all sensors within range",
            readings=[
                SensorReading(sensor_id="air_temperature_k",     unit="K",   value=300.1),
                SensorReading(sensor_id="process_temperature_k", unit="K",   value=310.5),
                SensorReading(sensor_id="rotational_speed_rpm",  unit="rpm", value=1850.0),
                SensorReading(sensor_id="torque_nm",             unit="Nm",  value=38.0),
                SensorReading(sensor_id="tool_wear_min",         unit="min", value=95.0),
            ],
            tags={"type": "M", "failure_types": "NONE", "machine_failure": "0"},
        ),
    },
    {
        "label": "CASE B — 공구 마모 임계값 초과 (에스컬레이션 예상)",
        "expected_route": "ESCALATE",
        "log": EquipmentLog(
            equipment_id="DEMO-ESC-002",
            timestamp=datetime(2026, 7, 15, 9, 5, 0, tzinfo=timezone.utc),
            log_level="ERROR",
            message="CRITICAL: tool wear exceeded operational limit — immediate action required",
            readings=[
                SensorReading(sensor_id="air_temperature_k",     unit="K",   value=298.0),
                SensorReading(sensor_id="process_temperature_k", unit="K",   value=308.0),
                SensorReading(sensor_id="rotational_speed_rpm",  unit="rpm", value=1500.0),
                SensorReading(sensor_id="torque_nm",             unit="Nm",  value=42.0),
                SensorReading(sensor_id="tool_wear_min",         unit="min", value=240.0),  # TWF: > 200min
            ],
            tags={"type": "M", "failure_types": "TWF", "machine_failure": "1"},
        ),
    },
]


def _route_color(route: str | None) -> str:
    if route == "AUTO":
        return GREEN
    if route == "ESCALATE":
        return RED
    if route == "HUMAN_REVIEW":
        return YELLOW
    return DIM


def _print_banner(text: str) -> None:
    print(f"\n{BOLD}{CYAN}{'═'*68}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{'═'*68}{RESET}")


def _print_result(case: dict, result: PipelineResult, elapsed: float) -> None:
    expected = case["expected_route"]
    rd = result.routing_decision
    actual_route = rd.route if rd else "—"
    matched_rule = rd.matched_rule if rd else "—"
    reason = rd.reason if rd else "—"

    ra = result.risk_assessment
    ar = result.anomaly_report
    vr = result.validation_result
    m  = result.metrics

    route_color = _route_color(actual_route)
    match_icon = "✅" if actual_route == expected else "⚠️ "

    print(f"\n  {DIM}{'─'*64}{RESET}")
    print(f"  {'risk_level':<28} {BOLD}{ra.risk_level if ra else '—'}{RESET}")
    if ra and ra.ml_predictor_upgraded:
        print(f"  {'  └─ ML 승격':<28} {YELLOW}SAFE → WARNING (proba={ra.ml_predictor_proba:.3f}){RESET}")
    print(f"  {'early_exit':<28} {m.early_exit}")
    if ar:
        print(f"  {'has_anomaly':<28} {ar.has_anomaly}")
    if vr:
        print(f"  {'recommendation':<28} {vr.recommendation}  (grounding={vr.overall_grounding_score:.3f})")
    if m.retry_count > 0:
        print(f"  {'retry_count':<28} {m.retry_count}")
    print(f"  {'stages':<28} {DIM}{' → '.join(m.stages_completed)}{RESET}")
    print(f"\n  {'적용 규칙':<28} {BOLD}{matched_rule}{RESET}")
    print(f"  {'사유':<28} {DIM}{reason}{RESET}")
    print(f"\n  {'최종 라우팅':<28} {route_color}{BOLD}{actual_route}{RESET}  {match_icon} (예상: {expected})")
    print(f"  {'소요 시간':<28} {elapsed:.1f}초")


async def run_demo() -> None:
    _print_banner("ForgeAI 에스컬레이션 경계 작동 데모")
    print(f"""
  이 데모는 동일한 파이프라인에서 두 케이스의 라우팅 결과를 비교합니다.
  - CASE A (정상): rule_engine=SAFE → early_exit → {GREEN}AUTO{RESET}
  - CASE B (임계값 초과): rule_engine=CRITICAL → 전체 파이프라인 → {RED}ESCALATE{RESET}
""")

    pipeline = ForgePipeline()
    summaries = []

    for i, case in enumerate(DEMO_CASES, 1):
        _print_banner(f"[{i}/2] {case['label']}")

        log = case["log"]
        print(f"\n  equipment_id : {log.equipment_id}")
        print(f"  message      : {log.message}")
        print(f"  {'센서값':}")
        for r in log.readings:
            print(f"    {r.sensor_id:<34} {r.value:>8.1f} {r.unit}")

        cid = f"demo-{uuid.uuid4().hex[:8]}"
        t0 = time.perf_counter()
        result = await pipeline.run(log, cid)
        elapsed = time.perf_counter() - t0

        _print_result(case, result, elapsed)
        summaries.append((case, result))

    # ── 비교 요약 ──────────────────────────────────────────────────────────────
    _print_banner("에스컬레이션 경계 비교 요약")
    print(f"\n  {'케이스':<36} {'위험등급':<12} {'조기종료':<10} {'최종라우팅'}")
    print(f"  {'─'*66}")
    for case, result in summaries:
        ra = result.risk_assessment
        rd = result.routing_decision
        route = rd.route if rd else "—"
        color = _route_color(route)
        print(
            f"  {case['label'][:36]:<36} "
            f"{(ra.risk_level if ra else '—'):<12} "
            f"{str(result.metrics.early_exit):<10} "
            f"{color}{BOLD}{route}{RESET}"
        )

    print(f"""
  {DIM}판단 기준{RESET}
  - SAFE → early_exit=True → 라우팅 규칙 R-4 → {GREEN}AUTO{RESET} (LLM 스킵)
  - CRITICAL → 전체 파이프라인 → 라우팅 규칙 R-1 → {RED}ESCALATE{RESET} (관리자 알림)
  - 경계 설계: 사람 확인 없이 자동처리되는 케이스는 SAFE early-exit 뿐
""")


if __name__ == "__main__":
    asyncio.run(run_demo())
