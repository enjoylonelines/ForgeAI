"""
고전 ML 베이스라인 분류기 — AI4I 2020 Predictive Maintenance Dataset

목적: 가공 없는 raw 피처로 정직한 베이스라인 수치 확보.
     정형 분류기 단독 성능의 상한을 측정해
     "예측은 정형 모델, 설명은 LLM" 하이브리드 구조의 정량적 근거를 만든다.
"""

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    confusion_matrix,
)
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

warnings.filterwarnings("ignore")

DATA_PATH = Path(__file__).parent.parent / "data" / "ai4i2020.csv"
RANDOM_STATE = 42

# ── 데이터 누수 가드레일 ─────────────────────────────────────────────────────
# 고장 모드 플래그 5개: 타깃(Machine failure)에서 파생된 컬럼 → 입력 절대 금지
LEAK_COLS = ["TWF", "HDF", "PWF", "OSF", "RNF"]
ID_COLS = ["UDI", "Product ID"]
TARGET = "Machine failure"

# Type 고정 매핑 (L/M/H → 0/1/2) — fit 필요 없는 고정 변환이므로 누수 없음
TYPE_MAP = {"L": 0, "M": 1, "H": 2}


def load_data():
  df = pd.read_csv(DATA_PATH)
  # XGBoost는 [ ] < 문자를 컬럼명에 허용하지 않아 사전에 정리
  df.columns = df.columns.str.replace(r"[\[\]<]", "", regex=True).str.strip()
  df["Type"] = df["Type"].map(TYPE_MAP)

  drop_cols = ID_COLS + LEAK_COLS + [TARGET]
  X = df.drop(columns=drop_cols)
  y = df[TARGET]

  # 누수 가드: 모드 컬럼 5개가 X에 없음을 보장
  for col in LEAK_COLS:
    assert col not in X.columns, f"데이터 누수 감지: {col}이 X에 포함돼 있음"

  return X, y


def print_section(title: str):
  print(f"\n{'=' * 60}")
  print(f"  {title}")
  print('=' * 60)


def print_metrics(name: str, y_test, y_pred, y_prob):
  print(f"\n[{name}]")
  print("Confusion Matrix (실제↓ / 예측→):")
  cm = confusion_matrix(y_test, y_pred)
  print(f"  정상(0) : TN={cm[0, 0]:5d}  FP={cm[0, 1]:5d}")
  print(f"  고장(1) : FN={cm[1, 0]:5d}  TP={cm[1, 1]:5d}")

  report = classification_report(y_test, y_pred, target_names=["정상(0)", "고장(1)"], digits=3)
  print(report)

  pr_auc = average_precision_score(y_test, y_prob)
  print(f"  PR-AUC (헤드라인 지표): {pr_auc:.4f}")


def main():
  # ── 1. 데이터 로드 ────────────────────────────────────────────────────────
  X, y = load_data()

  print_section("데이터셋 요약")
  print(f"  전체 샘플: {len(y):,}  |  고장(1): {y.sum():,} ({y.mean()*100:.2f}%)  |  피처: {X.shape[1]}개")
  print(f"  피처 목록: {list(X.columns)}")

  # ── 2. train/test 분리 — 모든 fit보다 먼저 ────────────────────────────────
  X_train, X_test, y_train, y_test = train_test_split(
      X, y, test_size=0.2, stratify=y, random_state=RANDOM_STATE
  )

  # 트리 계열은 스케일 불변 → 스케일링 생략 (의도적 결정)

  # train 기준 클래스 비율 계산 (XGB scale_pos_weight용)
  n_neg = (y_train == 0).sum()
  n_pos = (y_train == 1).sum()
  scale_pos = n_neg / n_pos

  print(f"\n  Train: {len(y_train):,} (고장 {n_pos}개)  |  Test: {len(y_test):,}")
  print(f"  XGB scale_pos_weight (train 기준): {scale_pos:.2f}")

  # ── 3. 더미 베이스라인 (accuracy 함정 시각화) ──────────────────────────────
  print_section("더미 베이스라인 (항상 정상=0 예측)")
  dummy = DummyClassifier(strategy="most_frequent")
  dummy.fit(X_train, y_train)
  y_dummy = dummy.predict(X_test)
  y_dummy_prob = np.zeros(len(y_test))  # 항상 0 예측 → 양성 확률 0

  dummy_acc = (y_dummy == y_test).mean()
  dummy_recall = ((y_dummy == 1) & (y_test == 1)).sum() / (y_test == 1).sum()
  print(f"  Accuracy  : {dummy_acc:.4f}  ← 높아 보이지만 함정")
  print(f"  고장 Recall: {dummy_recall:.4f}  ← 고장을 하나도 못 잡음")
  print("  → Accuracy를 헤드라인 지표로 쓰면 안 되는 이유")

  # ── 4. Random Forest ──────────────────────────────────────────────────────
  print_section("Random Forest")
  rf = RandomForestClassifier(
      class_weight="balanced",
      random_state=RANDOM_STATE,
  )
  rf.fit(X_train, y_train)
  y_rf = rf.predict(X_test)
  y_rf_prob = rf.predict_proba(X_test)[:, 1]
  print_metrics("Random Forest", y_test, y_rf, y_rf_prob)

  # ── 5. XGBoost ────────────────────────────────────────────────────────────
  print_section("XGBoost")
  xgb = XGBClassifier(
      scale_pos_weight=scale_pos,  # train 기준 음성/양성 비율
      random_state=RANDOM_STATE,
      eval_metric="logloss",
      verbosity=0,
  )
  xgb.fit(X_train, y_train)
  y_xgb = xgb.predict(X_test)
  y_xgb_prob = xgb.predict_proba(X_test)[:, 1]
  print_metrics("XGBoost", y_test, y_xgb, y_xgb_prob)

  # ── 6. 비교 요약표 ────────────────────────────────────────────────────────
  from sklearn.metrics import precision_score, recall_score, f1_score

  def summary_row(name, y_true, y_pred, y_prob):
    return {
        "모델": name,
        "PR-AUC": f"{average_precision_score(y_true, y_prob):.4f}",
        "고장 Recall": f"{recall_score(y_true, y_pred, zero_division=0):.4f}",
        "고장 Precision": f"{precision_score(y_true, y_pred, zero_division=0):.4f}",
        "고장 F1": f"{f1_score(y_true, y_pred, zero_division=0):.4f}",
        "Accuracy": f"{(y_pred == y_true).mean():.4f}",
    }

  print_section("비교 요약표")
  rows = [
      summary_row("Dummy (항상 정상)", y_test, y_dummy, y_dummy_prob),
      summary_row("Random Forest", y_test, y_rf, y_rf_prob),
      summary_row("XGBoost", y_test, y_xgb, y_xgb_prob),
  ]
  summary = pd.DataFrame(rows)
  print(summary.to_string(index=False))

  # ── 7.  ─────────────────────────────────────────────────────
  rf_pr_auc = average_precision_score(y_test, y_rf_prob)
  rf_recall = recall_score(y_test, y_rf, zero_division=0)
  rf_prec = precision_score(y_test, y_rf, zero_division=0)
  xgb_pr_auc = average_precision_score(y_test, y_xgb_prob)
  xgb_recall = recall_score(y_test, y_xgb, zero_division=0)
  xgb_prec = precision_score(y_test, y_xgb, zero_division=0)

  print_section("")
  print(f"""
이 분류기의 baseline 성능은 Random Forest 기준 PR-AUC {rf_pr_auc:.2f},
고장 recall {rf_recall:.2f}, precision {rf_prec:.2f}였고,
XGBoost는 PR-AUC {xgb_pr_auc:.2f}, recall {xgb_recall:.2f}, precision {xgb_prec:.2f}로
비슷한 수준이었다.
RNF(랜덤 고장)는 정의상 센서 패턴과 무관하게 발생하므로 정형 분류로는 예측이 불가능하며,
라벨 자체에도 'Machine failure=1인데 모드 플래그가 모두 0인' 불일치가 일부 존재해
정형 분류만으로는 여기까지가 한계였다.
그래서 센서 이상을 탐지하는 정형 모델 위에 고장 원인 추론·운전자 설명을 담당하는
LLM 에이전트 층을 얹는 하이브리드 아키텍처를 채택했다.
""")


if __name__ == "__main__":
  main()
