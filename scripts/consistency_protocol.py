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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from models.equipment_log import EquipmentLog, SensorReading
from pipeline.forge_pipeline import ForgePipeline


# ── 층화 샘플 로더 ─────────────────────────────────────────────────────────────

_FAILURE_COLS = ["TWF", "HDF", "PWF", "OSF", "RNF"]
_LOCAL_CSV = Path(__file__).parent.parent / "data" / "ai4i2020.csv"


def _load_raw_df() -> pd.DataFrame:
    if _LOCAL_CSV.exists():
        return pd.read_csv(_LOCAL_CSV)
    from ucimlrepo import fetch_ucirepo
    dataset = fetch_ucirepo(id=601)
    X = dataset.data.features.copy()
    y = dataset.data.targets.copy()
    return pd.concat([X, y], axis=1)


def _row_to_log(row: pd.Series, seq: int) -> EquipmentLog:
    from datetime import timedelta
    ts = datetime(2026, 1, 1, 8, tzinfo=timezone.utc) + timedelta(minutes=seq * 5)
    active = [f for f in _FAILURE_COLS if row.get(f, 0)]
    return EquipmentLog(
        equipment_id=str(row.get("Product ID", f"EQ-{seq}")),
        timestamp=ts,
        log_level="ERROR" if active else "INFO",
        message=f"Failure: {','.join(active)}" if active else "Normal operation",
        readings=[
            SensorReading(sensor_id="air_temperature_k",     unit="K",   value=float(row["Air temperature [K]"])),
            SensorReading(sensor_id="process_temperature_k", unit="K",   value=float(row["Process temperature [K]"])),
            SensorReading(sensor_id="rotational_speed_rpm",  unit="rpm", value=float(row["Rotational speed [rpm]"])),
            SensorReading(sensor_id="torque_nm",             unit="Nm",  value=float(row["Torque [Nm]"])),
            SensorReading(sensor_id="tool_wear_min",         unit="min", value=float(row["Tool wear [min]"])),
        ],
        tags={
            "type": str(row.get("Type", "M")),
            "failure_types": active[0] if active else "NONE",
            "machine_failure": str(int(row.get("Machine failure", 0))),
        },
    )


def load_stratified_samples(n_per_stratum: int = 6) -> list[tuple[str, EquipmentLog]]:
    """고장 유형별 n개 + 정상 n개 층화 샘플. 반환: [(stratum_label, log)]"""
    df = _load_raw_df()
    samples: list[tuple[str, EquipmentLog]] = []
    seq = 0

    for col in _FAILURE_COLS:
        if col not in df.columns:
            continue
        subset = df[df[col] == 1].head(n_per_stratum)
        for _, row in subset.iterrows():
            samples.append((col, _row_to_log(row, seq)))
            seq += 1

    normal_df = df[df["Machine failure"] == 0].head(n_per_stratum)
    for _, row in normal_df.iterrows():
        samples.append(("NORMAL", _row_to_log(row, seq)))
        seq += 1

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


def consistency_rate(values: list) -> float:
    """None 제외 후 최빈값 일치 비율."""
    non_null = [v for v in values if v is not None]
    if not non_null:
        return 1.0
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
    overall_anomaly = statistics.mean(r["anomaly_consistency"] for r in results)
    overall_rec    = statistics.mean(r["rec_consistency"]     for r in results)
    overall_route  = statistics.mean(r["route_consistency"]   for r in results)
    min_consistency = min(
        overall_anomaly, overall_rec, overall_route
    )

    grounding_stds = [
        statistics.stdev(r["grounding_scores"]) if len(r["grounding_scores"]) > 1 else 0.0
        for r in results if r["grounding_scores"]
    ]
    avg_gs_std = statistics.mean(grounding_stds) if grounding_stds else 0.0

    divergence_stages = [r["divergence_stage"] for r in results if r["divergence_stage"]]
    most_common_div = max(set(divergence_stages), key=divergence_stages.count) if divergence_stages else "없음"

    pass_fail = "✅ PASS" if min_consistency >= target_consistency else "❌ FAIL"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

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
        f"| has_anomaly 일관성 | {overall_anomaly*100:.1f}% | {'✅' if overall_anomaly >= target_consistency else '❌'} |",
        f"| recommendation 일관성 | {overall_rec*100:.1f}% | {'✅' if overall_rec >= target_consistency else '❌'} |",
        f"| route 일관성 | {overall_route*100:.1f}% | {'✅' if overall_route >= target_consistency else '❌'} |",
        f"| grounding_score σ (평균) | {avg_gs_std:.4f} | — |",
        f"| 최초 분기 지점 | {most_common_div} | — |",
        f"| 종합 | — | {pass_fail} |",
        f"",
        f"## 층화별 결과",
        f"",
        f"| # | 층 | Equipment ID | anomaly | rec | route | gs_σ | 분기점 |",
        f"|---|---|---|---|---|---|---|---|",
    ]

    for i, r in enumerate(results, 1):
        gs_std = statistics.stdev(r["grounding_scores"]) if len(r["grounding_scores"]) > 1 else 0.0
        rec_mode = max(set(r["runs_rec"]), key=r["runs_rec"].count) if r["runs_rec"] else "—"
        route_mode = max(set(r["runs_route"]), key=r["runs_route"].count) if r["runs_route"] else "—"
        lines.append(
            f"| {i} | {r['stratum']} | {r['equipment_id']} "
            f"| {r['anomaly_consistency']*100:.0f}% "
            f"| {r['rec_consistency']*100:.0f}% ({rec_mode}) "
            f"| {r['route_consistency']*100:.0f}% ({route_mode}) "
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
            if min(r["anomaly_consistency"], r["rec_consistency"], r["route_consistency"]) < target_consistency:
                lines.append(f"- `{r['equipment_id']}` ({r['stratum']}): "
                             f"anomaly={r['anomaly_consistency']*100:.0f}% "
                             f"rec={r['rec_consistency']*100:.0f}% "
                             f"route={r['route_consistency']*100:.0f}%")

    return "\n".join(lines) + "\n"


# ── 메인 ──────────────────────────────────────────────────────────────────────

async def main(n_runs: int, n_per_stratum: int, out_path: Path | None, target: float) -> None:
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
            "rec_consistency": consistency_rate(rec_vals) if rec_vals else 1.0,
            "route_consistency": consistency_rate(route_vals) if route_vals else 1.0,
            "grounding_scores": gs_vals,
            "divergence_stage": div_stage,
        }
        all_results.append(result)

        elapsed = time.monotonic() - t0
        a = result["anomaly_consistency"]
        rc = result["rec_consistency"]
        ro = result["route_consistency"]
        status = "✅" if min(a, rc, ro) >= target else "❌"
        print(f"{status} anomaly={a*100:.0f}% rec={rc*100:.0f}% route={ro*100:.0f}% ({elapsed:.1f}s)")

    elapsed_total = time.monotonic() - t_total
    report = build_report(all_results, n_runs, elapsed_total, target)

    print("\n" + "=" * 60)
    print(report)

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"리포트 저장: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="일관성 프로토콜 실측")
    parser.add_argument("--runs",     type=int,  default=20,  help="샘플당 반복 횟수 (기본 20)")
    parser.add_argument("--samples",  type=int,  default=6,   help="stratum당 샘플 수 (기본 6)")
    parser.add_argument("--target",   type=float,default=0.99, help="일관성 목표 (기본 0.99)")
    parser.add_argument("--out",      type=str,  default="docs/consistency_report.md", help="리포트 출력 경로")
    args = parser.parse_args()

    asyncio.run(main(
        n_runs=args.runs,
        n_per_stratum=args.samples,
        out_path=Path(args.out) if args.out else None,
        target=args.target,
    ))
