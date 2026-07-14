#!/usr/bin/env python3
"""
SECOM 스트레스 테스트 — 약신호 안전 실패 증명 (이슈 #10).

SECOM 반도체 공정 데이터(1567행 × 590피처)의 test set 314건에
XGBoost 예측 확률을 라우팅 함수에 직접 주입해 안전성을 검증한다.

증명 목표:
  ① 자동화율 0% — 실제 불량(label=1)이 AUTO 라우팅으로 빠져나가지 않음
  ② AUTO 라우팅된 실제 불량 0건

라우팅 신호 매핑:
  model_proba ≥ threshold  →  has_anomaly=True,  risk_level=WARNING/CRITICAL
  model_proba < threshold  →  has_anomaly=False, risk_level=SAFE
  → WARNING/CRITICAL + has_anomaly=True → R-F fallback → ESCALATE
  → SAFE               + has_anomaly=False → R-4 → AUTO

사용법:
    uv run python scripts/secom_stress_test.py
    uv run python scripts/secom_stress_test.py --threshold 0.3
    uv run python scripts/secom_stress_test.py --out docs/experiments/secom_stress_report.md
"""
from __future__ import annotations

import argparse
import ssl
import sys
import time
import urllib.request
import io
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score
from xgboost import XGBClassifier

from core.routing_rules import apply_routing_rules
from models.routing import RoutingInput


_LOCAL_X = Path(__file__).parent.parent / "data" / "secom_X.csv"
_LOCAL_Y = Path(__file__).parent.parent / "data" / "secom_y.csv"
RANDOM_STATE = 42


# ── 데이터 로더 ────────────────────────────────────────────────────────────────

def _load_secom() -> tuple[pd.DataFrame, pd.Series]:
    if _LOCAL_X.exists() and _LOCAL_Y.exists():
        X = pd.read_csv(_LOCAL_X)
        y = pd.read_csv(_LOCAL_Y).iloc[:, 0]
        return X, y

    print("SECOM 데이터 다운로드 중...")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    base = "https://archive.ics.uci.edu/ml/machine-learning-databases/secom"
    with urllib.request.urlopen(f"{base}/secom.data", context=ctx) as r:
        X = pd.read_csv(io.StringIO(r.read().decode()), sep=" ", header=None)
    with urllib.request.urlopen(f"{base}/secom_labels.data", context=ctx) as r:
        y = pd.read_csv(io.StringIO(r.read().decode()), sep=" ", header=None, usecols=[0]).iloc[:, 0]

    _LOCAL_X.parent.mkdir(parents=True, exist_ok=True)
    X.to_csv(_LOCAL_X, index=False)
    y.to_csv(_LOCAL_Y, index=False)
    return X, y


# ── XGBoost 학습·예측 ──────────────────────────────────────────────────────────

def train_and_predict(
    threshold: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    반환: (y_test, proba_test, y_train, proba_train)
    SECOM label: 1=불량, -1=정상. XGBoost는 0/1로 변환.
    """
    X, y = _load_secom()

    # SECOM: label 1=불량, -1=정상 → 0/1 변환
    y_bin = (y == 1).astype(int)

    # 결측값 처리 (열 평균으로 대체)
    imputer = SimpleImputer(strategy="mean")
    X_imp = imputer.fit_transform(X)

    X_tr, X_te, y_tr, y_te = train_test_split(
        X_imp, y_bin, test_size=0.2, random_state=RANDOM_STATE, stratify=y_bin
    )

    # 불균형 처리: scale_pos_weight
    neg, pos = (y_tr == 0).sum(), (y_tr == 1).sum()
    clf = XGBClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        scale_pos_weight=neg / pos,
        random_state=RANDOM_STATE,
        eval_metric="logloss",
        verbosity=0,
    )
    clf.fit(X_tr, y_tr)

    proba_te = clf.predict_proba(X_te)[:, 1]
    proba_tr = clf.predict_proba(X_tr)[:, 1]
    return y_te.values, proba_te, y_tr.values, proba_tr


# ── 라우팅 주입 ────────────────────────────────────────────────────────────────

def route_by_proba(proba: float, threshold: float) -> str:
    """XGBoost 확률을 라우팅 입력으로 변환해 route 반환."""
    has_anomaly = proba >= threshold
    if proba >= 0.8:
        risk_level = "CRITICAL"
    elif proba >= threshold:
        risk_level = "WARNING"
    else:
        risk_level = "SAFE"

    inp = RoutingInput(
        risk_level=risk_level,
        has_anomaly=has_anomaly,
        verdict_conflict=False,
        plan_step_count=0,
        recommendation=None,
        retry_count=0,
        max_retries=3,
    )
    return apply_routing_rules(inp).route


# ── 집계 ───────────────────────────────────────────────────────────────────────

def evaluate(y_test: np.ndarray, proba: np.ndarray, threshold: float) -> dict:
    routes = [route_by_proba(p, threshold) for p in proba]

    failure_mask = y_test == 1
    normal_mask  = y_test == 0

    failure_routes = [r for r, f in zip(routes, failure_mask) if f]
    normal_routes  = [r for r, n in zip(routes, normal_mask)  if n]

    failure_auto = sum(1 for r in failure_routes if r == "AUTO")
    normal_auto  = sum(1 for r in normal_routes  if r == "AUTO")
    total_auto   = sum(1 for r in routes if r == "AUTO")

    return {
        "threshold": threshold,
        "total": len(y_test),
        "failure_count": int(failure_mask.sum()),
        "normal_count": int(normal_mask.sum()),
        "failure_auto": failure_auto,      # ← 불량 유출
        "normal_auto": normal_auto,
        "total_auto": total_auto,
        "auto_rate_pct": total_auto / len(y_test) * 100,
        "failure_auto_rate_pct": failure_auto / int(failure_mask.sum()) * 100 if failure_mask.sum() > 0 else 0.0,
        "routes": routes,
        "y_test": y_test.tolist(),
        "proba": proba.tolist(),
    }


# ── 리포트 생성 ────────────────────────────────────────────────────────────────

def build_report(results: list[dict], elapsed: float, auc: float) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # threshold=0.5 기준 결과
    r50 = next((r for r in results if abs(r["threshold"] - 0.5) < 0.01), results[0])
    leak_verdict = "✅ 불량 유출 0건" if r50["failure_auto"] == 0 else f"❌ 불량 유출 {r50['failure_auto']}건"

    lines = [
        "# SECOM 스트레스 테스트 리포트",
        "",
        f"**측정일**: {ts}  ",
        f"**데이터셋**: SECOM (반도체 공정) 1567행 × 590피처  ",
        f"**test set**: {r50['total']}건 (불량 {r50['failure_count']}건 / 정상 {r50['normal_count']}건)  ",
        f"**모델**: XGBoost (scale_pos_weight, n_estimators=300)  ",
        f"**ROC-AUC (test)**: {auc:.4f}  ",
        f"**소요**: {elapsed:.1f}초  ",
        "",
        "## 증명 목표",
        "",
        "| 목표 | 값 (threshold=0.5) | 판정 |",
        "|------|---------------------|------|",
        f"| ① 불량 AUTO 라우팅 건수 | {r50['failure_auto']}건 | {leak_verdict} |",
        f"| ② 전체 자동화율 | {r50['auto_rate_pct']:.1f}% | — |",
        "",
        "## threshold별 라우팅 결과",
        "",
        "| threshold | 전체 AUTO | 불량 AUTO (유출) | 정상 AUTO | 자동화율 | 불량 유출률 |",
        "|-----------|-----------|-----------------|-----------|----------|------------|",
    ]

    for r in results:
        lines.append(
            f"| {r['threshold']:.2f} "
            f"| {r['total_auto']} "
            f"| **{r['failure_auto']}** "
            f"| {r['normal_auto']} "
            f"| {r['auto_rate_pct']:.1f}% "
            f"| {r['failure_auto_rate_pct']:.1f}% |"
        )

    # threshold=0.1 결과 (가장 aggressive)
    r10 = next((r for r in results if abs(r["threshold"] - 0.1) < 0.01), results[0])
    caught_at_01 = r10["failure_count"] - r10["failure_auto"]

    lines += [
        "",
        "## 약신호 안전 실패 분석",
        "",
        "### SECOM 데이터 특성",
        "",
        "- 590개 피처 중 대부분이 공정 노이즈로, 불량 신호가 매우 약함",
        "- 불량 비율 6.6% (21/314) — 심각한 클래스 불균형",
        f"- XGBoost ROC-AUC={auc:.4f} — 탐지 가능한 패턴은 존재하나 recall이 낮음",
        "",
        "### 라우팅 규칙 작동 방식",
        "",
        "```",
        "model_proba ≥ threshold → has_anomaly=True → R-F fallback → ESCALATE  ← 정상 작동",
        "model_proba < threshold → has_anomaly=False → R-4/R-5    → AUTO        ← ML false negative",
        "```",
        "",
        "라우팅 레이어 자체는 **has_anomaly=True인 경우 반드시 ESCALATE**를 보장한다.",
        f"threshold=0.1에서 {caught_at_01}건 불량이 라우팅 규칙에 의해 정상 ESCALATE됐다.",
        "",
        "### 불량 유출의 원인",
        "",
        "XGBoost가 실제 불량을 `proba < threshold`로 예측하는 **ML false negative**.",
        "라우팅 규칙의 결함이 아니라 SECOM 약신호 환경에서의 ML 모델 한계다.",
        "",
        "### 함의 — 2-tier 방어선 필요성",
        "",
        "| 방어선 | 역할 | AI4I 적용 | SECOM 적용 |",
        "|--------|------|-----------|-----------|",
        "| rule_engine | 결정론적 임계값 | ✅ 유효 | ❌ 임계값 없음 |",
        "| ML predictor | 통계적 확률 | — | ✅ 필요 (이슈 #11) |",
        "| 라우팅 레이어 | 신호 → ESCALATE/AUTO | ✅ 정상 | ✅ 정상 (신호 있을 때) |",
        "",
        "SECOM에서는 rule_engine 대신 ML predictor가 첫 번째 방어선이 돼야 한다.",
        "이슈 #11 ml_predictor가 이 역할을 담당한다.",
    ]

    return "\n".join(lines) + "\n"


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main(thresholds: list[float], out_path: Path | None) -> None:
    print("SECOM 데이터 로드 및 XGBoost 학습 중...")
    t0 = time.monotonic()
    y_test, proba_test, y_train, _ = train_and_predict(thresholds[0])
    elapsed = time.monotonic() - t0

    auc = roc_auc_score(y_test, proba_test)
    print(f"학습 완료 ({elapsed:.1f}s) — ROC-AUC: {auc:.4f}")
    print(f"test set: {len(y_test)}건 (불량 {y_test.sum()}건, 정상 {(y_test==0).sum()}건)\n")

    # 분류 리포트 (threshold=0.5)
    preds = (proba_test >= 0.5).astype(int)
    print(classification_report(y_test, preds, target_names=["정상", "불량"]))

    results = []
    for thr in thresholds:
        res = evaluate(y_test, proba_test, thr)
        results.append(res)
        verdict = "✅" if res["failure_auto"] == 0 else "❌"
        print(
            f"threshold={thr:.2f} | AUTO전체={res['total_auto']} "
            f"| 불량AUTO={res['failure_auto']} {verdict} "
            f"| 자동화율={res['auto_rate_pct']:.1f}%"
        )

    report = build_report(results, elapsed, auc)
    print("\n" + "=" * 60)
    print(report)

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"리포트 저장: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SECOM 스트레스 테스트")
    parser.add_argument(
        "--threshold", type=float, nargs="+",
        default=[0.1, 0.2, 0.3, 0.5, 0.7],
        help="검증할 threshold 목록 (기본: 0.1 0.2 0.3 0.5 0.7)",
    )
    parser.add_argument(
        "--out", type=str, default="docs/experiments/secom_stress_report.md",
        help="리포트 출력 경로",
    )
    args = parser.parse_args()

    main(thresholds=args.threshold, out_path=Path(args.out) if args.out else None)
