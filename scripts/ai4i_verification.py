#!/usr/bin/env python3
"""
AI4I 2020 주검증 스크립트 (이슈 #9).

ai4i2020.csv 10,000행 전수를 rule_engine(결정론적)으로 통과시켜
불량 유출(machine_failure=1 → AUTO route) 건수와 정상 AUTO 비율을 측정한다.

불량 유출 정의:
    machine_failure=1 인데 rule_engine이 SAFE 판정 → early_exit → AUTO 라우팅
    (SAFE 케이스는 LLM 없이 즉시 AUTO이므로 어떤 후속 처리도 불가)

정상 AUTO 비율:
    machine_failure=0 이고 rule_engine이 SAFE → early_exit → AUTO 처리되는 비율

3분기 분포:
    전체 행 기준 SAFE / WARNING / CRITICAL 비율

사용법:
    uv run python scripts/ai4i_verification.py
    uv run python scripts/ai4i_verification.py --out docs/ai4i_verification_report.md
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from core.rule_engine import assess_risk
from models.equipment_log import EquipmentLog, SensorReading


_FAILURE_COLS = ["TWF", "HDF", "PWF", "OSF", "RNF"]
_LOCAL_CSV = Path(__file__).parent.parent / "data" / "ai4i2020.csv"


# ── 데이터 로더 ────────────────────────────────────────────────────────────────

def _load_df() -> pd.DataFrame:
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


# ── 검증 로직 ──────────────────────────────────────────────────────────────────

def run_verification(df: pd.DataFrame) -> dict:
    """전수 rule_engine 패스. 반환값은 집계 딕셔너리."""
    total = len(df)
    results = []

    for seq, (_, row) in enumerate(df.iterrows()):
        log = _row_to_log(row, seq)
        ra = assess_risk(log)

        machine_failure = int(row.get("Machine failure", 0))
        active_cols = [f for f in _FAILURE_COLS if row.get(f, 0)]
        dataset_failure_type = active_cols[0] if active_cols else "NONE"

        # SAFE → early_exit → AUTO (no LLM)
        # non-SAFE → LLM pipeline → typically ESCALATE (R-1/R-4 applies for non-SAFE)
        deterministic_route = "AUTO" if ra.risk_level == "SAFE" else "ESCALATE"

        sensors = {r.sensor_id: r.value for r in log.readings}
        is_leak = machine_failure == 1 and ra.risk_level == "SAFE"
        results.append({
            "seq": seq,
            "equipment_id": log.equipment_id,
            "machine_failure": machine_failure,
            "dataset_failure_type": dataset_failure_type,
            "risk_level": ra.risk_level,
            "rule_failure_type": ra.failure_type,
            "triggered_types": ra.triggered_failure_types,
            "deterministic_route": deterministic_route,
            # 유출 행은 센서값을 함께 보존해 리포트에 활용
            "sensors": sensors if is_leak else None,
            "is_leak": is_leak,
            # 정상 AUTO: 정상인데 SAFE → AUTO (rule engine에서 early_exit 처리)
            "is_normal_auto": machine_failure == 0 and ra.risk_level == "SAFE",
        })

        if (seq + 1) % 1000 == 0:
            print(f"  {seq + 1:,}/{total:,} 처리 완료...", flush=True)

    return {"rows": results, "total": total}


# ── 집계 ───────────────────────────────────────────────────────────────────────

def aggregate(data: dict) -> dict:
    rows = data["rows"]
    total = data["total"]

    failure_rows = [r for r in rows if r["machine_failure"] == 1]
    normal_rows  = [r for r in rows if r["machine_failure"] == 0]

    leaks = [r for r in rows if r["is_leak"]]
    normal_auto = [r for r in normal_rows if r["is_normal_auto"]]

    # 3분기 분포 (SAFE / WARNING / CRITICAL)
    tier_dist = {"SAFE": 0, "WARNING": 0, "CRITICAL": 0}
    for r in rows:
        tier_dist[r["risk_level"]] = tier_dist.get(r["risk_level"], 0) + 1

    # 모드별 분포 (데이터셋 기준 failure_type)
    mode_stats: dict[str, dict] = {}
    for ft in _FAILURE_COLS + ["NONE"]:
        subset = [r for r in rows if r["dataset_failure_type"] == ft]
        if not subset:
            continue
        leaked = [r for r in subset if r["is_leak"]]
        mode_stats[ft] = {
            "count": len(subset),
            "safe": sum(1 for r in subset if r["risk_level"] == "SAFE"),
            "warning": sum(1 for r in subset if r["risk_level"] == "WARNING"),
            "critical": sum(1 for r in subset if r["risk_level"] == "CRITICAL"),
            "leaks": len(leaked),
            "leak_examples": [r["equipment_id"] for r in leaked[:5]],
        }

    # 고장 행 risk_level 분포
    failure_tier = {"SAFE": 0, "WARNING": 0, "CRITICAL": 0}
    for r in failure_rows:
        failure_tier[r["risk_level"]] = failure_tier.get(r["risk_level"], 0) + 1

    return {
        "total": total,
        "failure_count": len(failure_rows),
        "normal_count": len(normal_rows),
        "leak_count": len(leaks),
        "leak_rows": leaks,
        "leak_examples": [r["equipment_id"] for r in leaks[:10]],
        "normal_auto_count": len(normal_auto),
        "normal_auto_pct": len(normal_auto) / len(normal_rows) * 100 if normal_rows else 0.0,
        "tier_dist": tier_dist,
        "failure_tier": failure_tier,
        "mode_stats": mode_stats,
    }


# ── 리포트 생성 ────────────────────────────────────────────────────────────────

def build_report(agg: dict, elapsed: float) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    leak_verdict = "✅ 불량 유출 0건" if agg["leak_count"] == 0 else f"❌ 불량 유출 {agg['leak_count']}건"
    auto_verdict = "✅" if agg["normal_auto_pct"] > 0 else "❌"
    tier = agg["tier_dist"]
    total = agg["total"]

    lines = [
        "# AI4I 주검증 리포트",
        "",
        f"**측정일**: {ts}  ",
        f"**대상**: ai4i2020.csv {total:,}행 전수  ",
        f"**방법**: rule_engine(결정론적, LLM 미사용)  ",
        f"**소요**: {elapsed:.1f}초  ",
        "",
        "## 요약",
        "",
        "| 지표 | 값 | 판정 |",
        "|------|-----|------|",
        f"| 전체 행 | {total:,} | — |",
        f"| 고장 행 (machine_failure=1) | {agg['failure_count']:,} | — |",
        f"| 정상 행 (machine_failure=0) | {agg['normal_count']:,} | — |",
        f"| **불량 유출** (고장→AUTO) | **{agg['leak_count']}건** | {leak_verdict} |",
        f"| **정상 AUTO 비율** (early_exit) | **{agg['normal_auto_pct']:.1f}%** | {auto_verdict} |",
        "",
        "## 3분기 분포 (전체 10,000행 risk_level)",
        "",
        "| risk_level | 건수 | 비율 |",
        "|------------|------|------|",
        f"| SAFE | {tier['SAFE']:,} | {tier['SAFE']/total*100:.1f}% |",
        f"| WARNING | {tier['WARNING']:,} | {tier['WARNING']/total*100:.1f}% |",
        f"| CRITICAL | {tier['CRITICAL']:,} | {tier['CRITICAL']/total*100:.1f}% |",
        "",
        "## 고장 행 risk_level 분포",
        "",
        "| risk_level | 건수 | 비율 |",
        "|------------|------|------|",
    ]

    ft = agg["failure_tier"]
    fc = agg["failure_count"]
    for level in ("SAFE", "WARNING", "CRITICAL"):
        n = ft.get(level, 0)
        lines.append(f"| {level} | {n} | {n/fc*100:.1f}% |")

    lines += [
        "",
        "## 모드별 분포",
        "",
        "| 고장 유형 | 행 수 | SAFE | WARNING | CRITICAL | 유출 |",
        "|-----------|------|------|---------|----------|------|",
    ]

    for ft_name in _FAILURE_COLS + ["NONE"]:
        s = agg["mode_stats"].get(ft_name)
        if s is None:
            continue
        lines.append(
            f"| {ft_name} | {s['count']} | {s['safe']} | {s['warning']} | {s['critical']} | {s['leaks']} |"
        )

    if agg["leak_count"] > 0:
        lines += [
            "",
            f"## ❌ 불량 유출 목록 ({agg['leak_count']}건 전수)",
            "",
            "| # | Equipment ID | failure_type | tool_wear | torque | rpm | air_temp | proc_temp |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for i, r in enumerate(agg["leak_rows"], 1):
            s = r.get("sensors") or {}
            tw  = f"{s['tool_wear_min']:.1f}"          if "tool_wear_min"          in s else "—"
            tq  = f"{s['torque_nm']:.1f}"              if "torque_nm"              in s else "—"
            rpm = f"{s['rotational_speed_rpm']:.0f}"   if "rotational_speed_rpm"   in s else "—"
            at  = f"{s['air_temperature_k']:.1f}"      if "air_temperature_k"      in s else "—"
            pt  = f"{s['process_temperature_k']:.1f}"  if "process_temperature_k"  in s else "—"
            lines.append(
                f"| {i} | `{r['equipment_id']}` | {r['dataset_failure_type']}"
                f" | {tw} | {tq} | {rpm} | {at} | {pt} |"
            )
        lines += [
            "",
            "### 유출 원인 분석",
            "",
            "- **TWF 유출**: `tool_wear_min` ≤ 200 이지만 데이터셋 레이블은 TWF — 임계값 재검토 대상 (이슈 #21)",
            "- **NONE 유출**: `machine_failure=1` 이지만 특정 고장 유형 없음 — AI4I RNF 특성상 센서 패턴 없음, 단일 임계값으로 포착 불가 (구조적 한계)",
        ]
    else:
        lines += [
            "",
            "## ✅ 불량 유출 없음",
            "",
            "rule_engine이 고장 339건 전수를 non-SAFE(WARNING 또는 CRITICAL)로 판정.",
            "SAFE early_exit 경로로 빠져나가 AUTO 라우팅된 고장 행 0건.",
        ]

    return "\n".join(lines) + "\n"


# ── README 자동화율 빈칸 채움 ──────────────────────────────────────────────────

_README = Path(__file__).parent.parent / "README.md"
_VERIFY_ANCHOR = "<!-- ai4i-verification-results -->"


def patch_readme(agg: dict) -> bool:
    """README에 검증 결과 섹션을 삽입하거나 업데이트한다. 변경 여부 반환."""
    if not _README.exists():
        return False

    content = _README.read_text(encoding="utf-8")

    normal_auto_pct = f"{agg['normal_auto_pct']:.1f}%"
    leak_line = f"불량 유출 0건 ✅" if agg["leak_count"] == 0 else f"불량 유출 {agg['leak_count']}건 ❌"

    block = (
        f"{_VERIFY_ANCHOR}\n\n"
        "### AI4I 2020 검증 결과\n\n"
        "| 지표 | 값 |\n"
        "|------|----|\n"
        f"| 고장 전수 검출 | {leak_line} |\n"
        f"| 정상 AUTO 비율 (rule engine early-exit) | {normal_auto_pct} |\n"
        f"| SAFE / WARNING / CRITICAL | "
        f"{agg['tier_dist']['SAFE']:,} / {agg['tier_dist']['WARNING']:,} / {agg['tier_dist']['CRITICAL']:,} |\n"
        "\n"
        f"상세: [`docs/ai4i_verification_report.md`](docs/ai4i_verification_report.md)\n"
    )

    if _VERIFY_ANCHOR in content:
        # 기존 블록 교체
        import re
        new_content = re.sub(
            rf"{re.escape(_VERIFY_ANCHOR)}.*?(?=\n---|\n## |\Z)",
            block,
            content,
            flags=re.DOTALL,
        )
    else:
        # RAG 개선 기록 섹션 앞에 삽입
        insert_before = "\n---\n\n## RAG 개선 기록"
        if insert_before in content:
            new_content = content.replace(insert_before, f"\n---\n\n{block}\n---\n\n## RAG 개선 기록")
        else:
            # 파일 끝에 추가
            new_content = content.rstrip() + f"\n\n---\n\n{block}"

    if new_content != content:
        _README.write_text(new_content, encoding="utf-8")
        return True
    return False


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main(out_path: Path | None) -> None:
    print("AI4I 2020 데이터 로드 중...")
    df = _load_df()
    print(f"{len(df):,}행 로드 완료. rule_engine 전수 패스 시작...\n")

    t0 = time.monotonic()
    raw = run_verification(df)
    elapsed = time.monotonic() - t0

    print(f"\n완료: {elapsed:.1f}초\n")

    agg = aggregate(raw)

    print(f"불량 유출: {agg['leak_count']}건 / {agg['failure_count']}건")
    print(f"정상 AUTO: {agg['normal_auto_count']:,}건 / {agg['normal_count']:,}건 = {agg['normal_auto_pct']:.1f}%")
    print(f"3분기 분포 — SAFE: {agg['tier_dist']['SAFE']:,}  WARNING: {agg['tier_dist']['WARNING']:,}  CRITICAL: {agg['tier_dist']['CRITICAL']:,}")

    report = build_report(agg, elapsed)
    print("\n" + "=" * 60)
    print(report)

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"리포트 저장: {out_path}")

    patched = patch_readme(agg)
    if patched:
        print("README 검증 결과 섹션 업데이트 완료.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI4I 주검증")
    parser.add_argument("--out", type=str, default="docs/ai4i_verification_report.md", help="리포트 출력 경로")
    args = parser.parse_args()

    main(out_path=Path(args.out) if args.out else None)
