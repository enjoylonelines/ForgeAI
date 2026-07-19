#!/usr/bin/env python3
"""
일관성 프로토콜 실측 스크립트 (이슈 #8).

AI4I 층화 30건 × 20회 = 600회 파이프라인 실행.
결정 일관성(has_anomaly / recommendation / route),
grounding score 표준편차, 최초 분기 지점을 리포트로 출력한다.

사용법:
    uv run python scripts/consistency_protocol.py
    uv run python scripts/consistency_protocol.py --runs 5 --samples 6  # 빠른 확인
    uv run python scripts/consistency_protocol.py --out docs/consistency_report.md
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from models.equipment_log import EquipmentLog, SensorReading
from pipeline.forge_pipeline import ForgePipeline


# ── 층화 샘플 정의 ─────────────────────────────────────────────────────────────
# rule_engine 임계값을 확실히 트리거하는 하드코딩 케이스.
# AI4I 랜덤 샘플은 라벨이 있어도 센서값이 임계값을 안 넘어 early_exit(SAFE)가 되어
# LLM 파이프라인이 실행되지 않으므로 일관성 측정 의미가 없음.

_FIXED_SAMPLES: list[tuple[str, dict]] = [
    # TWF: tool_wear ≥ 200 → rule_engine CRITICAL
    ("TWF", dict(equipment_id="CP-TWF-001", log_level="ERROR",
                 message="Tool wear limit exceeded",
                 air=298.0, proc=308.0, rpm=1500.0, torque=42.0, wear=215.0,
                 failure_types="TWF")),
    ("TWF", dict(equipment_id="CP-TWF-002", log_level="ERROR",
                 message="Tool wear critical",
                 air=299.0, proc=309.0, rpm=1480.0, torque=40.0, wear=230.0,
                 failure_types="TWF")),
    # HDF: (proc-air) < 8.6 AND rpm < 1380 → rule_engine WARNING
    ("HDF", dict(equipment_id="CP-HDF-001", log_level="WARN",
                 message="Heat dissipation anomaly",
                 air=302.0, proc=308.0, rpm=1200.0, torque=35.0, wear=80.0,
                 failure_types="HDF")),
    ("HDF", dict(equipment_id="CP-HDF-002", log_level="WARN",
                 message="Heat dissipation low",
                 air=303.0, proc=308.5, rpm=1300.0, torque=33.0, wear=90.0,
                 failure_types="HDF")),
    # PWF: torque × rpm × 2π/60 < 3500 → rule_engine WARNING
    ("PWF", dict(equipment_id="CP-PWF-001", log_level="ERROR",
                 message="Power output below minimum",
                 air=299.0, proc=309.0, rpm=1400.0, torque=15.0, wear=90.0,
                 failure_types="PWF")),
    ("PWF", dict(equipment_id="CP-PWF-002", log_level="ERROR",
                 message="Power failure detected",
                 air=300.0, proc=310.0, rpm=1350.0, torque=14.0, wear=85.0,
                 failure_types="PWF")),
    # OSF: tool_wear × torque > 11000 → rule_engine WARNING
    ("OSF", dict(equipment_id="CP-OSF-001", log_level="WARN",
                 message="Overstrain condition detected",
                 air=300.0, proc=310.0, rpm=1000.0, torque=60.0, wear=190.0,
                 failure_types="OSF")),
    ("OSF", dict(equipment_id="CP-OSF-002", log_level="WARN",
                 message="Overstrain limit exceeded",
                 air=301.0, proc=311.0, rpm=950.0,  torque=65.0, wear=180.0,
                 failure_types="OSF")),
    # RNF: 임계값 없음 → ML predictor 보조 탐지 경로
    ("RNF", dict(equipment_id="CP-RNF-001", log_level="WARN",
                 message="Random failure pattern",
                 air=305.0, proc=315.0, rpm=1600.0, torque=55.0, wear=150.0,
                 failure_types="RNF")),
    ("RNF", dict(equipment_id="CP-RNF-002", log_level="WARN",
                 message="Unclassified anomaly",
                 air=304.0, proc=314.0, rpm=1550.0, torque=52.0, wear=145.0,
                 failure_types="RNF")),
    # NORMAL: 모든 센서 정상 → SAFE early_exit (대조군)
    ("NORMAL", dict(equipment_id="CP-NRM-001", log_level="INFO",
                    message="Normal operation",
                    air=300.0, proc=310.0, rpm=1800.0, torque=38.0, wear=95.0,
                    failure_types="NONE")),
    ("NORMAL", dict(equipment_id="CP-NRM-002", log_level="INFO",
                    message="Normal operation",
                    air=299.5, proc=309.5, rpm=1850.0, torque=36.0, wear=100.0,
                    failure_types="NONE")),
]


def load_stratified_samples(n_per_stratum: int = 1) -> list[tuple[str, EquipmentLog]]:
    """rule_engine을 확실히 트리거하는 고정 케이스 반환. [(stratum_label, log)]
    n_per_stratum: stratum당 샘플 수 (기본 1, 최대 2)
    """
    from datetime import timedelta
    samples: list[tuple[str, EquipmentLog]] = []

    seen: dict[str, int] = {}
    for stratum, spec in _FIXED_SAMPLES:
        count = seen.get(stratum, 0)
        if count >= n_per_stratum:
            continue
        seen[stratum] = count + 1
        seq = len(samples)
        ts = datetime(2026, 1, 1, 8, tzinfo=timezone.utc) + timedelta(minutes=seq * 5)
        log = EquipmentLog(
            equipment_id=spec["equipment_id"],
            timestamp=ts,
            log_level=spec["log_level"],
            message=spec["message"],
            readings=[
                SensorReading(sensor_id="air_temperature_k",     unit="K",   value=spec["air"]),
                SensorReading(sensor_id="process_temperature_k", unit="K",   value=spec["proc"]),
                SensorReading(sensor_id="rotational_speed_rpm",  unit="rpm", value=spec["rpm"]),
                SensorReading(sensor_id="torque_nm",             unit="Nm",  value=spec["torque"]),
                SensorReading(sensor_id="tool_wear_min",         unit="min", value=spec["wear"]),
            ],
            tags={"type": "M", "failure_types": spec["failure_types"],
                  "machine_failure": "0" if stratum == "NORMAL" else "1"},
        )
        samples.append((stratum, log))

    return samples

    return samples


# ── 실행 및 집계 ───────────────────────────────────────────────────────────────

async def run_once(pipeline: ForgePipeline, log: EquipmentLog) -> dict:
    cid = f"cp-{uuid.uuid4().hex[:8]}"
    r = await pipeline.run(log, cid)
    ar = r.anomaly_report
    vr = r.validation_result
    rd = r.routing_decision
    return {
        "has_anomaly": ar.has_anomaly if ar else None,
        "recommendation": vr.recommendation if vr else None,
        "route": rd.route if rd else None,
        "matched_rule": rd.matched_rule if rd else None,
        "grounding_score": vr.overall_grounding_score if vr else None,
        "risk_level": r.metrics.risk_level,
        "stages": r.metrics.stages_completed,
        "early_exit": r.metrics.early_exit,
    }


def consistency_rate(values: list) -> float | None:
    """None 제외 후 최빈값 일치 비율. 측정 가능한 값이 없으면 None 반환."""
    non_null = [v for v in values if v is not None]
    if not non_null:
        return None
    mode = max(set(non_null), key=non_null.count)
    return sum(1 for v in non_null if v == mode) / len(non_null)


def first_divergence_stage(runs: list[list[str]]) -> str | None:
    """여러 run의 stages_completed 리스트 중 처음 갈라지는 stage."""
    if not runs:
        return None
    min_len = min(len(r) for r in runs)
    for i in range(min_len):
        stages_at_i = [r[i] for r in runs]
        if len(set(stages_at_i)) > 1:
            return stages_at_i[0]  # 첫 번째 run의 해당 stage
    # 길이가 다른 경우
    lengths = [len(r) for r in runs]
    if len(set(lengths)) > 1:
        return f"depth_{min_len + 1}"
    return None


# ── 리포트 생성 ────────────────────────────────────────────────────────────────

def build_report(
    results: list[dict],
    n_runs: int,
    elapsed_total: float,
    target_consistency: float,
) -> str:
    """
    results: list of {
        stratum, equipment_id,
        runs: [run_dict, ...],
        anomaly_consistency, rec_consistency, route_consistency,
        grounding_scores, divergence_stage
    }
    """
    def _mean_or_none(key: str) -> float | None:
        vals = [r[key] for r in results if r[key] is not None]
        return statistics.mean(vals) if vals else None

    overall_anomaly = _mean_or_none("anomaly_consistency")
    overall_rec     = _mean_or_none("rec_consistency")
    overall_route   = _mean_or_none("route_consistency")
    available = [v for v in [overall_anomaly, overall_rec, overall_route] if v is not None]
    min_consistency = min(available) if available else 1.0

    grounding_stds = [
        statistics.stdev(r["grounding_scores"]) if len(r["grounding_scores"]) > 1 else 0.0
        for r in results if r["grounding_scores"]
    ]
    avg_gs_std = statistics.mean(grounding_stds) if grounding_stds else 0.0

    all_gs = [gs for r in results for gs in r["grounding_scores"]]
    avg_gs_mean = statistics.mean(all_gs) if all_gs else None

    divergence_stages = [r["divergence_stage"] for r in results if r["divergence_stage"]]
    most_common_div = max(set(divergence_stages), key=divergence_stages.count) if divergence_stages else "없음"

    pass_fail = "✅ PASS" if min_consistency >= target_consistency else "❌ FAIL"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def _fmt(v: float | None) -> str:
        return f"{v*100:.1f}%" if v is not None else "N/A"

    def _judge(v: float | None) -> str:
        if v is None:
            return "—"
        return "✅" if v >= target_consistency else "❌"

    lines = [
        f"# 일관성 프로토콜 실측 리포트",
        f"",
        f"**측정일**: {ts}  ",
        f"**프로토콜**: AI4I 층화 {len(results)}건 × {n_runs}회 = {len(results) * n_runs}회  ",
        f"**총 소요**: {elapsed_total:.1f}초  ",
        f"**판정 기준**: 일관성 ≥ {target_consistency*100:.0f}%  ",
        f"",
        f"## 요약",
        f"",
        f"| 지표 | 값 | 판정 |",
        f"|------|-----|------|",
        f"| has_anomaly 일관성 | {_fmt(overall_anomaly)} | {_judge(overall_anomaly)} |",
        f"| recommendation 일관성 | {_fmt(overall_rec)} | {_judge(overall_rec)} |",
        f"| route 일관성 | {_fmt(overall_route)} | {_judge(overall_route)} |",
        f"| grounding_score 평균 | {avg_gs_mean*100:.1f}% | — |" if avg_gs_mean is not None else "| grounding_score 평균 | N/A | — |",
        f"| grounding_score σ (평균) | {avg_gs_std:.4f} | — |",
        f"| 최초 분기 지점 | {most_common_div} | — |",
        f"| 종합 | — | {pass_fail} |",
        f"",
        f"## 층화별 결과",
        f"",
        f"| # | 층 | Equipment ID | anomaly | rec | route | gs_μ | gs_σ | 분기점 |",
        f"|---|---|---|---|---|---|---|---|---|",
    ]

    for i, r in enumerate(results, 1):
        gs_std = statistics.stdev(r["grounding_scores"]) if len(r["grounding_scores"]) > 1 else 0.0
        gs_mean_fmt = f"{statistics.mean(r['grounding_scores'])*100:.1f}%" if r["grounding_scores"] else "N/A"
        rec_mode = max(set(r["runs_rec"]), key=r["runs_rec"].count) if r["runs_rec"] else "—"
        route_mode = max(set(r["runs_route"]), key=r["runs_route"].count) if r["runs_route"] else "—"
        a_fmt  = _fmt(r["anomaly_consistency"])
        rc_fmt = _fmt(r["rec_consistency"])
        ro_fmt = _fmt(r["route_consistency"])
        lines.append(
            f"| {i} | {r['stratum']} | {r['equipment_id']} "
            f"| {a_fmt} "
            f"| {rc_fmt} ({rec_mode}) "
            f"| {ro_fmt} ({route_mode}) "
            f"| {gs_mean_fmt} "
            f"| {gs_std:.4f} "
            f"| {r['divergence_stage'] or '없음'} |"
        )

    if min_consistency < target_consistency:
        lines += [
            f"",
            f"## ❌ 미달 원인 분석",
            f"",
            f"일관성이 {target_consistency*100:.0f}% 미달한 샘플이 존재합니다.",
            f"가장 빈번한 분기점: **{most_common_div}**",
            f"",
            f"### 불일치 샘플 목록",
            f"",
        ]
        for r in results:
            row_vals = [v for v in [r["anomaly_consistency"], r["rec_consistency"], r["route_consistency"]] if v is not None]
            if row_vals and min(row_vals) < target_consistency:
                lines.append(f"- `{r['equipment_id']}` ({r['stratum']}): "
                             f"anomaly={_fmt(r['anomaly_consistency'])} "
                             f"rec={_fmt(r['rec_consistency'])} "
                             f"route={_fmt(r['route_consistency'])}")

    return "\n".join(lines) + "\n"


# ── 메인 ──────────────────────────────────────────────────────────────────────

async def main(n_runs: int, n_per_stratum: int, out_path: Path | None, target: float, chart_path: Path | None = None) -> None:
    print(f"층화 샘플 로드 중 (stratum당 최대 {n_per_stratum}개)...")
    samples = load_stratified_samples(n_per_stratum=n_per_stratum)
    print(f"샘플 {len(samples)}건 로드 완료. {n_runs}회 × {len(samples)}건 = {n_runs * len(samples)}회 실행\n")

    pipeline = ForgePipeline()
    all_results: list[dict] = []
    t_total = time.monotonic()

    for idx, (stratum, log) in enumerate(samples, 1):
        print(f"[{idx:02d}/{len(samples)}] {stratum} {log.equipment_id} × {n_runs}회 ...", end=" ", flush=True)
        t0 = time.monotonic()
        runs: list[dict] = []
        for _ in range(n_runs):
            run = await run_once(pipeline, log)
            runs.append(run)

        anomaly_vals = [r["has_anomaly"] for r in runs]
        rec_vals     = [r["recommendation"] for r in runs if r["recommendation"] is not None]
        route_vals   = [r["route"] for r in runs if r["route"] is not None]
        gs_vals      = [r["grounding_score"] for r in runs if r["grounding_score"] is not None]
        stages_list  = [r["stages"] for r in runs]

        div_stage = first_divergence_stage(stages_list)

        result = {
            "stratum": stratum,
            "equipment_id": log.equipment_id,
            "runs": runs,
            "runs_rec": rec_vals,
            "runs_route": route_vals,
            "anomaly_consistency": consistency_rate(anomaly_vals),
            "rec_consistency": consistency_rate(rec_vals) if rec_vals else None,
            "route_consistency": consistency_rate(route_vals) if route_vals else None,
            "grounding_scores": gs_vals,
            "divergence_stage": div_stage,
        }
        all_results.append(result)

        elapsed = time.monotonic() - t0
        a = result["anomaly_consistency"]
        rc = result["rec_consistency"]
        ro = result["route_consistency"]
        measurable = [v for v in [a, rc, ro] if v is not None]
        status = "✅" if (measurable and min(measurable) >= target) else "❌"
        fmt = lambda v: f"{v*100:.0f}%" if v is not None else "N/A"
        print(f"{status} anomaly={fmt(a)} rec={fmt(rc)} route={fmt(ro)} ({elapsed:.1f}s)")

    elapsed_total = time.monotonic() - t_total
    report = build_report(all_results, n_runs, elapsed_total, target)

    print("\n" + "=" * 60)
    print(report)

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"리포트 저장: {out_path}")

    if chart_path:
        save_distribution_chart(all_results, chart_path)


# ── 차트 생성 ─────────────────────────────────────────────────────────────────

def save_distribution_chart(results: list[dict], out_path: Path) -> None:
    """판정 분포 차트 저장 (route 일관성 + stratum별 route 분포)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import numpy as np
    except ImportError:
        print("[WARN] matplotlib 미설치 — 차트 생략")
        return

    strata = [r["stratum"] for r in results]
    unique_strata = list(dict.fromkeys(strata))

    route_colors = {"AUTO": "#4CAF50", "ESCALATE": "#F44336", "HUMAN_REVIEW": "#FF9800", None: "#9E9E9E"}
    route_labels = ["AUTO", "ESCALATE", "HUMAN_REVIEW"]

    # stratum별 route 분포 집계
    stratum_routes: dict[str, Counter] = {}
    for r in results:
        s = r["stratum"]
        if s not in stratum_routes:
            stratum_routes[s] = Counter()
        for run in r["runs"]:
            stratum_routes[s][run.get("route") or "None"] += 1

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle("ForgeAI 판단 일관성 검증 결과", fontsize=14, fontweight="bold")

    # ── 왼쪽: 일관성률 막대 ──────────────────────────────────────────────────
    x = np.arange(len(results))
    width = 0.25
    a_vals = [r["anomaly_consistency"] or 0 for r in results]
    rc_vals = [r["rec_consistency"] or 0 for r in results]
    ro_vals = [r["route_consistency"] or 0 for r in results]

    ax1.bar(x - width, a_vals, width, label="has_anomaly", color="#2196F3", alpha=0.8)
    ax1.bar(x,         rc_vals, width, label="recommendation", color="#9C27B0", alpha=0.8)
    ax1.bar(x + width, ro_vals, width, label="route", color="#FF5722", alpha=0.8)
    ax1.axhline(y=0.99, color="black", linestyle="--", linewidth=1.2, label="목표 99%")
    ax1.set_xticks(x)
    ax1.set_xticklabels([r["equipment_id"][:8] for r in results], rotation=45, ha="right", fontsize=7)
    ax1.set_ylim(0, 1.05)
    ax1.set_ylabel("일관성률")
    ax1.set_title("샘플별 판단 일관성")
    ax1.legend(fontsize=8)
    ax1.grid(axis="y", alpha=0.3)

    # ── 오른쪽: stratum별 route 분포 스택 막대 ──────────────────────────────
    xs = np.arange(len(unique_strata))
    bottoms = np.zeros(len(unique_strata))
    for rl in route_labels:
        vals = [stratum_routes.get(s, Counter()).get(rl, 0) for s in unique_strata]
        ax2.bar(xs, vals, bottom=bottoms, color=route_colors[rl], label=rl, alpha=0.85)
        bottoms += np.array(vals)
    ax2.set_xticks(xs)
    ax2.set_xticklabels(unique_strata, rotation=30, ha="right")
    ax2.set_ylabel("실행 횟수")
    ax2.set_title("층화별 라우팅 분포")
    patches = [mpatches.Patch(color=route_colors[rl], label=rl) for rl in route_labels]
    ax2.legend(handles=patches, fontsize=8)
    ax2.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"차트 저장: {out_path}")


# ── 메인 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="일관성 프로토콜 실측")
    parser.add_argument("--runs",     type=int,  default=20,  help="샘플당 반복 횟수 (기본 20)")
    parser.add_argument("--samples",  type=int,  default=5,   help="stratum당 샘플 수 (기본 5 → 30×20=600)")
    parser.add_argument("--target",   type=float,default=0.99, help="일관성 목표 (기본 0.99)")
    parser.add_argument("--out",      type=str,  default="docs/consistency_report.md", help="리포트 출력 경로")
    parser.add_argument("--chart",    type=str,  default="docs/consistency_distribution.png", help="차트 출력 경로")
    parser.add_argument("--model",    type=str,  default=None, help="Ollama 모델 (예: qwen3:4b)")
    args = parser.parse_args()

    if args.model:
        import os
        os.environ["OLLAMA_CHAT_MODEL"] = args.model

    asyncio.run(main(
        n_runs=args.runs,
        n_per_stratum=args.samples,
        out_path=Path(args.out) if args.out else None,
        target=args.target,
        chart_path=Path(args.chart) if args.chart else None,
    ))
