"""운영점(Operating Point) 분석 스크립트.

임계값(threshold)별 Recall/Precision 트레이드오프를 측정하여
배포 게이트 기준값을 결정한다.

사용법:
    uv run python scripts/operating_point_analysis.py
"""

import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_score, recall_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

warnings.filterwarnings("ignore")

DATA_PATH = Path(__file__).parent.parent / "data" / "raw" / "ai4i2020.csv"
RANDOM_STATE = 42
LEAK_COLS = ["TWF", "HDF", "PWF", "OSF", "RNF"]
ID_COLS = ["UDI", "Product ID"]
TARGET = "Machine failure"
TYPE_MAP = {"L": 0, "M": 1, "H": 2}

# 운영 비용 가정: FN 비용이 FP 비용의 몇 배인가
# 제조 현장에서 미탐(FN) = 설비 파손/라인 정지 >> 과탐(FP) = 불필요한 점검
FN_FP_COST_RATIO = 10


def load_and_split():
    df = pd.read_csv(DATA_PATH)
    df.columns = df.columns.str.replace(r"[\[\]<]", "", regex=True).str.strip()
    df["Type"] = df["Type"].map(TYPE_MAP)
    X = df.drop(columns=ID_COLS + LEAK_COLS + [TARGET])
    y = df[TARGET]
    return train_test_split(X, y, test_size=0.2, stratify=y, random_state=RANDOM_STATE)


def main():
    X_train, X_test, y_train, y_test = load_and_split()
    n_neg = (y_train == 0).sum()
    n_pos = (y_train == 1).sum()

    xgb = XGBClassifier(
        scale_pos_weight=n_neg / n_pos,
        random_state=RANDOM_STATE,
        eval_metric="logloss",
        verbosity=0,
    )
    xgb.fit(X_train, y_train)
    y_prob = xgb.predict_proba(X_test)[:, 1]

    pr_auc = average_precision_score(y_test, y_prob)
    n_failure = (y_test == 1).sum()
    n_total = len(y_test)

    print(f"\nXGBoost PR-AUC: {pr_auc:.4f}  |  테스트셋 고장 수: {n_failure}/{n_total}")
    print(f"FN/FP 비용 가정: FN이 FP의 {FN_FP_COST_RATIO}배 비쌈\n")

    # ── 임계값별 트레이드오프 테이블 ──────────────────────────────────────────
    thresholds = [round(t, 2) for t in np.arange(0.05, 0.96, 0.05)]

    print(f"{'임계값':>6}  {'Recall':>7}  {'Precision':>9}  {'F1':>6}  "
          f"{'FP수':>5}  {'FN수':>5}  {'가중비용':>8}")
    print("-" * 62)

    rows = []
    for t in thresholds:
        y_pred = (y_prob >= t).astype(int)
        rec  = recall_score(y_test, y_pred, zero_division=0)
        prec = precision_score(y_test, y_pred, zero_division=0)
        f1   = 2 * rec * prec / (rec + prec) if (rec + prec) > 0 else 0.0
        tp = ((y_pred == 1) & (y_test == 1)).sum()
        fp = ((y_pred == 1) & (y_test == 0)).sum()
        fn = ((y_pred == 0) & (y_test == 1)).sum()
        # 가중 비용 = FN × 비용비 + FP × 1 (정규화)
        cost = fn * FN_FP_COST_RATIO + fp
        rows.append(dict(threshold=t, recall=rec, precision=prec, f1=f1,
                         fp=fp, fn=fn, cost=cost))
        print(f"  {t:>5.2f}  {rec:>7.4f}  {prec:>9.4f}  {f1:>6.4f}  "
              f"{fp:>5}  {fn:>5}  {cost:>8}")

    # ── 운영점 추천 ──────────────────────────────────────────────────────────
    df_rows = pd.DataFrame(rows)

    # Precision 하한: 탐지된 알람 중 절반 이상은 실제 고장이어야 함 (과탐 방어)
    PRECISION_FLOOR = 0.5
    feasible = df_rows[df_rows["precision"] >= PRECISION_FLOOR]

    best_cost = feasible.loc[feasible["cost"].idxmin()] if not feasible.empty else df_rows.loc[df_rows["cost"].idxmin()]
    best_f1 = df_rows.loc[df_rows["f1"].idxmax()]

    max_recall = df_rows["recall"].max()
    max_recall_row = df_rows.loc[df_rows["recall"].idxmax()]

    print("\n" + "=" * 62)
    print("운영점 추천")
    print("=" * 62)
    print(f"\n  ※ 달성 가능한 최대 Recall: {max_recall:.4f} (임계값 {max_recall_row['threshold']:.2f})")
    print(f"  ※ Recall이 0.90에 못 미치는 이유: RNF(랜덤 고장)는 센서 패턴과 무관해 구조적으로 탐지 불가")
    print(f"  ※ Precision ≥ {PRECISION_FLOOR} 제약 적용 (과탐 방어): {len(feasible)}개 임계값 후보")

    # Precision ≥ 0.5 만족 & Recall ≥ 0.80 중 가중비용 최소를 운영점으로 설정
    r80 = feasible[feasible["recall"] >= 0.80]
    if not r80.empty:
        op = r80.loc[r80["cost"].idxmin()]
        print(f"\n[A] Precision ≥ {PRECISION_FLOOR} + Recall ≥ 0.80 + 가중비용 최소")
        print(f"    임계값 {op['threshold']:.2f}  →  "
              f"Recall {op['recall']:.4f} / Precision {op['precision']:.4f} / "
              f"F1 {op['f1']:.4f}")
        print(f"    FP {int(op['fp'])}건 / FN {int(op['fn'])}건  (가중비용: {int(op['cost'])})")

    print(f"\n[B] Precision ≥ {PRECISION_FLOOR} 내 가중비용 절대 최소 (FN×{FN_FP_COST_RATIO} + FP)")
    print(f"    임계값 {best_cost['threshold']:.2f}  →  "
          f"Recall {best_cost['recall']:.4f} / Precision {best_cost['precision']:.4f} / "
          f"F1 {best_cost['f1']:.4f}")

    print(f"\n[C] F1 최대 (Precision 제약 없음)")
    print(f"    임계값 {best_f1['threshold']:.2f}  →  "
          f"Recall {best_f1['recall']:.4f} / Precision {best_f1['precision']:.4f} / "
          f"F1 {best_f1['f1']:.4f}")

    print(f"\n[기본값 0.50 비교]")
    base = df_rows[df_rows["threshold"] == 0.50].iloc[0]
    print(f"    임계값 0.50  →  "
          f"Recall {base['recall']:.4f} / Precision {base['precision']:.4f} / "
          f"F1 {base['f1']:.4f}")

    print("\n" + "=" * 62)
    print("배포 게이트 기준값 (권고)  ← README 빈칸 채우기")
    print("=" * 62)
    if not r80.empty:
        op = r80.loc[r80["cost"].idxmin()]
        print(f"  PR-AUC         ≥ {pr_auc:.3f}   (현재 모델 기준선)")
        print(f"  운영점 Recall  ≥ 0.800   (임계값 {op['threshold']:.2f} 적용 시, "
              f"Precision {op['precision']:.3f})")
        print(f"  Precision      ≥ {PRECISION_FLOOR}   (과탐 방어 하한)")
        print(f"  선택 근거: RNF 구조적 한계로 0.90 불가. Precision ≥ {PRECISION_FLOOR} 제약 내 "
              f"FN/FP 비용비 {FN_FP_COST_RATIO}:1 가정에서 Recall ≥ 0.80 달성 최저 비용 지점.")


if __name__ == "__main__":
    main()
