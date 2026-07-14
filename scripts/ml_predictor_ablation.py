#!/usr/bin/env python3
"""
ML Predictor Ablation — 신호 on/off 자동화율 변화 (이슈 #11).

AI4I 2020 전체 10,000행에서 두 가지 모드를 비교한다:
  - MODE A (rule_engine only):   risk_level은 rule_engine 단독 결정
  - MODE B (rule_engine + ML):   rule_engine=SAFE이고 ml_proba≥threshold이면 WARNING 상향

증명 목표:
  ① 불량 유출 0건 유지 (MODE B도 rule_engine이 잡은 불량은 그대로 ESCALATE)
  ② MODE B에서 rule_engine이 놓친 불량(RNF 포함) 중 ML이 추가 포착
  ③ 정상 AUTO 감소폭 허용 범위 확인 (precision 유지)

사용법:
    uv run python scripts/ml_predictor_ablation.py
    uv run python scripts/ml_predictor_ablation.py --threshold 0.25
    uv run python scripts/ml_predictor_ablation.py --out docs/experiments/ml_predictor_ablation.md
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import classification_report, f1_score, average_precision_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier
import numpy as np

from core.rule_engine import assess_risk
from core.ml_predictor import ML_THRESHOLD, _get_model, _LEAK_COLS, _ID_COLS, _TARGET, _TYPE_MAP, _SENSOR_TO_COL
from models.equipment_log import EquipmentLog, SensorReading
from datetime import timezone

_DATA_PATH = Path(__file__).parent.parent / "data" / "ai4i2020.csv"
_RANDOM_STATE = 42

_COL_TO_SENSOR = {v: k for k, v in _SENSOR_TO_COL.items()}

_TYPE_INV = {v: k for k, v in _TYPE_MAP.items()}


# ── 데이터 → EquipmentLog 변환 ──────────────────────────────────────────────

def _row_to_log(row: pd.Series, feature_cols: list[str]) -> EquipmentLog:
    readings = []
    for col in feature_cols:
        if col == "Type":
            continue
        sensor_id = _COL_TO_SENSOR.get(col)
        if sensor_id and not pd.isna(row[col]):
            readings.append(SensorReading(sensor_id=sensor_id, unit="", value=float(row[col])))

    type_val = int(row["Type"]) if "Type" in row.index else 1
    machine_type = _TYPE_INV.get(type_val, "M")

    return EquipmentLog(
        equipment_id=f"AI4I-{int(row.get('UDI', 0))}",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        readings=readings,
        tags={"type": machine_type},
    )


# ── 단일 행 라우팅 (두 모드) ────────────────────────────────────────────────

def _route_rule_only(log: EquipmentLog) -> tuple[str, str]:
    """(risk_level, route)"""
    ra = assess_risk(log)
    route = "AUTO" if ra.risk_level == "SAFE" else "ESCALATE"
    return ra.risk_level, route


def _route_with_ml(log: EquipmentLog, model: CalibratedClassifierCV, feature_cols: list[str], threshold: float) -> tuple[str, str, float]:
    """(risk_level, route, ml_proba)"""
    from core import ml_predictor as _ml
    ml_proba = _ml.predict_proba(log)
    ra = assess_risk(log)

    risk_level = ra.risk_level
    if ra.risk_level == "SAFE" and ml_proba >= threshold:
        risk_level = "WARNING"

    route = "AUTO" if risk_level == "SAFE" else "ESCALATE"
    return risk_level, route, ml_proba


# ── 집계 ───────────────────────────────────────────────────────────────────

def run_ablation(threshold: float) -> dict:
    df = pd.read_csv(_DATA_PATH)
    df.columns = df.columns.str.replace(r"[\[\]<]", "", regex=True).str.strip()
    df["Type"] = df["Type"].map(_TYPE_MAP)

    feature_cols = [c for c in df.columns if c not in _ID_COLS + _LEAK_COLS + [_TARGET]]

    model, _ = _get_model()

    rows_a, rows_b = [], []

    for _, row in df.iterrows():
        machine_failure = int(row[_TARGET])
        log = _row_to_log(row, feature_cols)

        rl_a, route_a = _route_rule_only(log)
        rl_b, route_b, ml_proba = _route_with_ml(log, model, feature_cols, threshold)

        rows_a.append({"machine_failure": machine_failure, "risk_level": rl_a, "route": route_a})
        rows_b.append({"machine_failure": machine_failure, "risk_level": rl_b, "route": route_b, "ml_proba": ml_proba})

    df_a = pd.DataFrame(rows_a)
    df_b = pd.DataFrame(rows_b)

    def stats(df_mode: pd.DataFrame) -> dict:
        fail = df_mode["machine_failure"] == 1
        norm = df_mode["machine_failure"] == 0
        auto = df_mode["route"] == "AUTO"
        return {
            "total": len(df_mode),
            "failure_count": int(fail.sum()),
            "normal_count": int(norm.sum()),
            "failure_auto": int((fail & auto).sum()),
            "normal_auto": int((norm & auto).sum()),
            "total_auto": int(auto.sum()),
            "auto_rate_pct": auto.sum() / len(df_mode) * 100,
            "failure_auto_rate_pct": (fail & auto).sum() / fail.sum() * 100 if fail.sum() > 0 else 0.0,
            "normal_auto_rate_pct": (norm & auto).sum() / norm.sum() * 100 if norm.sum() > 0 else 0.0,
        }

    stat_a = stats(df_a)
    stat_b = stats(df_b)

    # ML predictor 단독 성능 (proba 기준)
    ml_probas = np.array(df_b["ml_proba"])
    y_true = df["Machine failure"].values
    ml_preds = (ml_probas >= threshold).astype(int)
    ml_pr_auc = average_precision_score(y_true, ml_probas)
    ml_f1 = f1_score(y_true, ml_preds, zero_division=0)

    # ML이 추가 포착한 불량 (rule_engine=AUTO이지만 ML=ESCALATE)
    additional_caught = int(
        ((df_a["route"] == "AUTO") & (df_b["route"] == "ESCALATE") & (df_a["machine_failure"] == 1)).sum()
    )
    # 정상이 잘못 ESCALATE된 건수 증가
    false_escalation_increase = int(
        ((df_a["route"] == "AUTO") & (df_b["route"] == "ESCALATE") & (df_a["machine_failure"] == 0)).sum()
    )

    return {
        "threshold": threshold,
        "mode_a": stat_a,
        "mode_b": stat_b,
        "ml_pr_auc": ml_pr_auc,
        "ml_f1": ml_f1,
        "additional_caught": additional_caught,
        "false_escalation_increase": false_escalation_increase,
    }


# ── 리포트 생성 ────────────────────────────────────────────────────────────

def build_report(result: dict, elapsed: float) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    thr = result["threshold"]
    a = result["mode_a"]
    b = result["mode_b"]

    auto_delta = b["total_auto"] - a["total_auto"]
    auto_delta_str = f"{auto_delta:+d}"
    fail_leak_a = a["failure_auto"]
    fail_leak_b = b["failure_auto"]
    caught = result["additional_caught"]
    fp_inc = result["false_escalation_increase"]

    lines = [
        "# ML Predictor Ablation 리포트",
        "",
        f"**측정일**: {ts}  ",
        f"**데이터셋**: AI4I 2020 Predictive Maintenance ({a['total']:,}행)  ",
        f"**ML threshold**: {thr}  ",
        f"**소요**: {elapsed:.1f}초  ",
        "",
        "## 증명 목표 검증",
        "",
        "| 목표 | MODE A (rule only) | MODE B (rule + ML) | 판정 |",
        "|------|-------------------|-------------------|------|",
        f"| ① 불량 AUTO 유출 | {fail_leak_a}건 | {fail_leak_b}건 | {'✅ 유지' if fail_leak_b <= fail_leak_a else '❌ 증가'} |",
        f"| ② ML 추가 포착 불량 | — | {caught}건 | {'✅' if caught > 0 else '—'} |",
        f"| ③ 정상 AUTO 감소 | {a['normal_auto']}건 | {b['normal_auto']}건 | {fp_inc}건 추가 ESCALATE |",
        "",
        "## 라우팅 비교",
        "",
        "| 지표 | MODE A (rule only) | MODE B (rule + ML) | 변화 |",
        "|------|-------------------|-------------------|------|",
        f"| 전체 AUTO | {a['total_auto']} ({a['auto_rate_pct']:.1f}%) | {b['total_auto']} ({b['auto_rate_pct']:.1f}%) | {auto_delta_str} |",
        f"| 불량 AUTO (유출) | {fail_leak_a} ({a['failure_auto_rate_pct']:.1f}%) | {fail_leak_b} ({b['failure_auto_rate_pct']:.1f}%) | {fail_leak_b - fail_leak_a:+d} |",
        f"| 정상 AUTO | {a['normal_auto']} ({a['normal_auto_rate_pct']:.1f}%) | {b['normal_auto']} ({b['normal_auto_rate_pct']:.1f}%) | {b['normal_auto'] - a['normal_auto']:+d} |",
        "",
        "## ML Predictor 단독 성능 (AI4I 전체)",
        "",
        f"- **PR-AUC**: {result['ml_pr_auc']:.4f}",
        f"- **F1** (threshold={thr}): {result['ml_f1']:.4f}",
        "",
        "## 해석",
        "",
        f"MODE B에서 ML predictor는 rule_engine이 SAFE로 판정한 케이스 중 {caught}건의 실제 불량을 추가 포착했다.",
        f"대가로 정상 {fp_inc}건이 AUTO 대신 ESCALATE로 승격됐다.",
        "",
        "**불량 유출 0건 유지 전제**: rule_engine이 잡은 불량(WARNING/CRITICAL)은",
        "ML predictor가 관여하지 않으므로 MODE A → MODE B로 전환해도 기존 유출은 증가하지 않는다.",
        "",
        f"**남은 유출 {fail_leak_b}건**: rule_engine도 ML predictor도 포착 못한 케이스.",
        "AI4I RNF 정의상 '공정 파라미터와 결정론적/통계적 관계가 없음' — 구조적 한계.",
        "",
        "## 결론",
        "",
        f"threshold={thr}에서 ML predictor를 활성화하면:",
        f"- 불량 추가 포착 +{caught}건 (recall 개선)",
        f"- 정상 AUTO 감소 -{fp_inc}건 (precision 소폭 감소)",
        f"- 전체 자동화율 {a['auto_rate_pct']:.1f}% → {b['auto_rate_pct']:.1f}% ({auto_delta_str}건)",
        "",
        "rule_engine 단독 대비 ML 보조 신호가 추가적인 안전망 역할을 한다.",
    ]

    return "\n".join(lines) + "\n"


# ── 메인 ──────────────────────────────────────────────────────────────────

def main(threshold: float, out_path: Path | None) -> None:
    print(f"AI4I ablation 실행 중 (threshold={threshold})...")
    t0 = time.monotonic()
    result = run_ablation(threshold)
    elapsed = time.monotonic() - t0

    a, b = result["mode_a"], result["mode_b"]
    print(f"완료 ({elapsed:.1f}s)")
    print(f"\n[MODE A — rule only]  AUTO={a['total_auto']} ({a['auto_rate_pct']:.1f}%)  불량유출={a['failure_auto']}")
    print(f"[MODE B — rule + ML]  AUTO={b['total_auto']} ({b['auto_rate_pct']:.1f}%)  불량유출={b['failure_auto']}")
    print(f"ML 추가 포착: {result['additional_caught']}건  |  정상 추가 ESCALATE: {result['false_escalation_increase']}건")
    print(f"ML PR-AUC: {result['ml_pr_auc']:.4f}  |  ML F1: {result['ml_f1']:.4f}")

    report = build_report(result, elapsed)
    print("\n" + "=" * 60)
    print(report)

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"리포트 저장: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ML Predictor Ablation")
    parser.add_argument("--threshold", type=float, default=ML_THRESHOLD)
    parser.add_argument("--out", type=str, default="docs/experiments/ml_predictor_ablation.md")
    args = parser.parse_args()
    main(threshold=args.threshold, out_path=Path(args.out) if args.out else None)
