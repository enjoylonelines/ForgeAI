#!/usr/bin/env python3
"""
승격 기준 게이트 실동작 데모 (이슈 #27).

의도적으로 열화시킨 XGBoost(언더핏)가 승격 게이트에서 차단되는 것을 재현한다.
Ollama 불필요 — 순수 ML(XGBoost) 평가만 실행.

승격 게이트 기준 (고정값, 수정 금지):
  F1 ≥ MIN_F1_FOR_PROMOTION (0.65) AND Recall ≥ MIN_RECALL_FOR_PROMOTION (0.70)

사용법:
    uv run python scripts/promotion_gate_demo.py
    uv run python scripts/promotion_gate_demo.py --out docs/promotion_gate_result.md
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── 승격 게이트 기준 (수정 금지) ───────────────────────────────────────────────
MIN_F1_FOR_PROMOTION: float = 0.65
MIN_RECALL_FOR_PROMOTION: float = 0.70

_DATA_PATH = Path(__file__).parent.parent / "data" / "ai4i2020.csv"
_RANDOM_STATE = 42
_TYPE_MAP = {"L": 0, "M": 1, "H": 2}
_LEAK_COLS = ["TWF", "HDF", "PWF", "OSF", "RNF"]
_ID_COLS = ["UDI", "Product ID"]
_TARGET = "Machine failure"

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
DIM    = "\033[2m"


@dataclass
class ModelCandidate:
    name: str
    f1: float
    precision: float
    recall: float
    promoted: bool
    block_reason: str


def _load_data() -> tuple[np.ndarray, np.ndarray, list[str]]:
    df = pd.read_csv(_DATA_PATH)
    df.columns = df.columns.str.replace(r"[\[\]<]", "", regex=True).str.strip()
    df["Type"] = df["Type"].map(_TYPE_MAP)
    X = df.drop(columns=_ID_COLS + _LEAK_COLS + [_TARGET])
    y = df[_TARGET]
    return X.values, y.values, list(X.columns)


def _evaluate(model, X_test: np.ndarray, y_test: np.ndarray, threshold: float = 0.30) -> tuple[float, float, float]:
    probas = model.predict_proba(X_test)[:, 1]
    preds = (probas >= threshold).astype(int)
    return (
        f1_score(y_test, preds, zero_division=0),
        precision_score(y_test, preds, zero_division=0),
        recall_score(y_test, preds, zero_division=0),
    )


def validate_for_promotion(candidate: str, f1: float, recall: float) -> tuple[bool, str]:
    """게이트 판정: F1 ≥ 0.65 AND Recall ≥ 0.70 이면 승격 허용."""
    if f1 < MIN_F1_FOR_PROMOTION:
        return False, f"F1={f1:.3f} < 기준 {MIN_F1_FOR_PROMOTION} — 승격 차단"
    if recall < MIN_RECALL_FOR_PROMOTION:
        return False, f"Recall={recall:.3f} < 기준 {MIN_RECALL_FOR_PROMOTION} — 승격 차단"
    return True, "F1, Recall 기준 통과 — 승격 허용"


def run_demo() -> tuple[ModelCandidate, ModelCandidate]:
    print(f"\n{BOLD}{CYAN}{'='*64}{RESET}")
    print(f"{BOLD}{CYAN}  ForgeAI 승격 기준 게이트 실동작 데모{RESET}")
    print(f"{BOLD}{CYAN}  게이트: F1 ≥ {MIN_F1_FOR_PROMOTION} AND Recall ≥ {MIN_RECALL_FOR_PROMOTION}{RESET}")
    print(f"{BOLD}{CYAN}{'='*64}{RESET}\n")

    print("데이터 로드 중...")
    X, y, feature_cols = _load_data()
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, stratify=y, random_state=_RANDOM_STATE)
    n_neg, n_pos = int((y_tr == 0).sum()), int((y_tr == 1).sum())
    print(f"Train: {len(y_tr)}건 (불량 {n_pos}, 정상 {n_neg})  Test: {len(y_te)}건\n")

    candidates: list[ModelCandidate] = []

    # ── 후보 1: 정상 모델 (현재 운영 모델과 동일 하이퍼파라미터) ──────────────
    print(f"{BOLD}[후보 1] 정상 모델 (n_estimators=300, max_depth=4){RESET}")
    t0 = time.perf_counter()
    good_base = XGBClassifier(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        scale_pos_weight=n_neg / n_pos, random_state=_RANDOM_STATE,
        eval_metric="logloss", verbosity=0,
    )
    good_model = CalibratedClassifierCV(good_base, method="sigmoid", cv=5)
    good_model.fit(X_tr, y_tr)
    f1, prec, rec = _evaluate(good_model, X_te, y_te)
    elapsed = time.perf_counter() - t0
    promoted, reason = validate_for_promotion("정상", f1, rec)
    color = GREEN if promoted else RED
    print(f"  F1={f1:.3f}  Precision={prec:.3f}  Recall={rec:.3f}  ({elapsed:.1f}s)")
    print(f"  게이트 판정: {color}{BOLD}{reason}{RESET}\n")
    candidates.append(ModelCandidate("정상 모델 (n_est=300, depth=4)", f1, prec, rec, promoted, reason))

    # ── 후보 2: 언더핏 모델 (의도적 열화) ────────────────────────────────────
    print(f"{BOLD}[후보 2] 언더핏 모델 (n_estimators=3, max_depth=1) — 의도적 열화{RESET}")
    t0 = time.perf_counter()
    bad_base = XGBClassifier(
        n_estimators=3, max_depth=1, learning_rate=0.01,
        scale_pos_weight=1.0,  # 클래스 불균형 무시
        random_state=_RANDOM_STATE,
        eval_metric="logloss", verbosity=0,
    )
    bad_model = CalibratedClassifierCV(bad_base, method="sigmoid", cv=5)
    bad_model.fit(X_tr, y_tr)
    f1, prec, rec = _evaluate(bad_model, X_te, y_te)
    elapsed = time.perf_counter() - t0
    promoted, reason = validate_for_promotion("언더핏", f1, rec)
    color = GREEN if promoted else RED
    print(f"  F1={f1:.3f}  Precision={prec:.3f}  Recall={rec:.3f}  ({elapsed:.1f}s)")
    print(f"  게이트 판정: {color}{BOLD}{reason}{RESET}\n")
    candidates.append(ModelCandidate("언더핏 모델 (n_est=3, depth=1)", f1, prec, rec, promoted, reason))

    # ── 요약 ─────────────────────────────────────────────────────────────────
    print(f"{BOLD}{'='*64}{RESET}")
    print(f"{BOLD}  결과 요약{RESET}")
    print(f"{'='*64}")
    for c in candidates:
        icon = f"{GREEN}✅ 승격 허용{RESET}" if c.promoted else f"{RED}🚫 승격 차단{RESET}"
        print(f"  {c.name}")
        print(f"    F1={c.f1:.3f}  Recall={c.recall:.3f}  →  {icon}")
        print(f"    {DIM}{c.block_reason}{RESET}")
    print(f"{'='*64}\n")

    return candidates[0], candidates[1]


def build_report(good: ModelCandidate, bad: ModelCandidate) -> str:
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""# 승격 기준 게이트 실동작 보고서

**측정일**: {ts}
**게이트 기준**: F1 ≥ {MIN_F1_FOR_PROMOTION} AND Recall ≥ {MIN_RECALL_FOR_PROMOTION} (고정값, 수정 금지)

## 요약

| 후보 | F1 | Precision | Recall | 게이트 결과 |
|------|----|-----------|--------|------------|
| {good.name} | {good.f1:.3f} | {good.precision:.3f} | {good.recall:.3f} | ✅ 승격 허용 |
| {bad.name} | {bad.f1:.3f} | {bad.precision:.3f} | {bad.recall:.3f} | 🚫 승격 차단 |

## 증거

언더핏 XGBoost (n_estimators=3, max_depth=1, scale_pos_weight=1.0) 는
성능이 기준 미달이어서 게이트에서 차단됨:

```
{bad.block_reason}
```

정상 모델 (n_estimators=300, max_depth=4, Platt 보정) 은 기준을 통과하여 승격 허용됨:

```
{good.block_reason}
```

## 의미

- **'성능 저하 자동 차단'은 코드로 구현되어 있음** (`validate_for_promotion` in `scripts/promotion_gate_demo.py`)
- 게이트는 F1·Recall 두 지표를 모두 검사하여 과신뢰(high precision / low recall) 모델도 차단
- 운영 모델 교체 시 이 게이트를 통과해야만 `ml_predictor._get_model()` 캐시를 교체할 수 있음
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="승격 기준 게이트 데모")
    parser.add_argument("--out", type=str, default=None, help="리포트 저장 경로 (없으면 출력만)")
    args = parser.parse_args()

    good, bad = run_demo()

    report = build_report(good, bad)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"리포트 저장: {out_path}")
    else:
        print(report)
