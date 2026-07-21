"""
고전 ML 베이스라인 분류기 — SECOM 반도체 공정 데이터셋

목적: 실공장 데이터(고차원·결측·클래스 불균형)에서 정형 분류기 베이스라인 수치 확보.
     AI4I 2020(시뮬레이션)과 달리 SECOM은 실제 반도체 웨이퍼 공정 데이터이므로
     피처 선택·결측 처리·시간순 분할이 모두 필요한 현실적 조건이다.

분할 방식: 시간순 (ADR-002)
     secom_labels.csv에 타임스탬프가 행마다 존재 → 앞 80% 훈련, 뒤 20% 테스트.
     stratify 랜덤 분할과 달리 배포 현실(미래 비가시)을 반영한다.

피처 전처리:
     1. 결측률 50% 초과 컬럼 제거 (28개) — 절반 이상 없는 센서는 신호 없음
     2. 분산 0 컬럼 제거 (116개) — 상수 컬럼은 예측력 0
     3. 남은 결측값: median imputation (트리 계열은 스케일 불변 → 스케일링 생략)

레이블: 1 = 불량, -1 = 양호 → 내부에서 1/0으로 변환
"""

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from xgboost import XGBClassifier

warnings.filterwarnings("ignore")

DATA_PATH   = Path(__file__).parent.parent / "data" / "raw" / "secom" / "secom.csv"
LABELS_PATH = Path(__file__).parent.parent / "data" / "raw" / "secom" / "secom_labels.csv"
RANDOM_STATE = 42

# 결측 컬럼 제거 임계값
NAN_DROP_THRESHOLD = 0.5


def load_data():
    df = pd.read_csv(DATA_PATH, header=None, sep=" ")
    labels = pd.read_csv(LABELS_PATH, header=None, sep=" ", names=["label", "timestamp"])

    # 타임스탬프 파싱 (시간순 분할용)
    labels["timestamp"] = pd.to_datetime(labels["timestamp"], format="%d/%m/%Y %H:%M:%S")

    # 레이블 변환: 1(불량) → 1, -1(양호) → 0
    y = (labels["label"] == 1).astype(int)
    timestamps = labels["timestamp"]

    return df, y, timestamps


def remove_low_quality_features(X: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    nan_rate = X.isna().mean()
    std = X.std()

    drop_high_nan = nan_rate[nan_rate > NAN_DROP_THRESHOLD].index.tolist()
    drop_zero_var = std[std == 0].index.tolist()
    drop_all = list(set(drop_high_nan + drop_zero_var))

    X_clean = X.drop(columns=drop_all)
    info = {
        "원본 피처 수": X.shape[1],
        f"결측률 {int(NAN_DROP_THRESHOLD*100)}%+ 제거": len(drop_high_nan),
        "분산 0 제거": len(drop_zero_var),
        "남은 피처 수": X_clean.shape[1],
    }
    return X_clean, info


def time_split(X: pd.DataFrame, y: pd.Series, timestamps: pd.Series, test_size: float = 0.2):
    order = timestamps.argsort()
    X = X.iloc[order].reset_index(drop=True)
    y = y.iloc[order].reset_index(drop=True)
    ts = timestamps.iloc[order].reset_index(drop=True)

    split_idx = int(len(X) * (1 - test_size))
    return (
        X.iloc[:split_idx], X.iloc[split_idx:],
        y.iloc[:split_idx], y.iloc[split_idx:],
        ts.iloc[split_idx - 1],   # 분할 기준 타임스탬프
    )


def print_section(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


def print_metrics(name: str, y_test, y_pred, y_prob):
    print(f"\n[{name}]")
    cm = confusion_matrix(y_test, y_pred)
    print("Confusion Matrix (실제↓ / 예측→):")
    print(f"  양호(0) : TN={cm[0, 0]:5d}  FP={cm[0, 1]:5d}")
    print(f"  불량(1) : FN={cm[1, 0]:5d}  TP={cm[1, 1]:5d}")
    print(classification_report(y_test, y_pred, target_names=["양호(0)", "불량(1)"], digits=3))
    pr_auc = average_precision_score(y_test, y_prob)
    print(f"  PR-AUC (헤드라인 지표): {pr_auc:.4f}")


def summary_row(name, y_true, y_pred, y_prob):
    return {
        "모델": name,
        "PR-AUC": f"{average_precision_score(y_true, y_prob):.4f}",
        "불량 Recall": f"{recall_score(y_true, y_pred, zero_division=0):.4f}",
        "불량 Precision": f"{precision_score(y_true, y_pred, zero_division=0):.4f}",
        "불량 F1": f"{f1_score(y_true, y_pred, zero_division=0):.4f}",
        "Accuracy": f"{(y_pred == y_true).mean():.4f}",
    }


def main():
    # ── 1. 데이터 로드 ────────────────────────────────────────────────────────
    X, y, timestamps = load_data()

    print_section("데이터셋 요약")
    print(f"  전체 샘플: {len(y):,}  |  불량(1): {y.sum():,} ({y.mean()*100:.2f}%)  |  원본 피처: {X.shape[1]}개")
    print(f"  타임스탬프 범위: {timestamps.min()} ~ {timestamps.max()}")

    # ── 2. 피처 정제 ──────────────────────────────────────────────────────────
    X_clean, feat_info = remove_low_quality_features(X)
    print_section("피처 정제")
    for k, v in feat_info.items():
        print(f"  {k}: {v}")

    # ── 3. 시간순 분할 ────────────────────────────────────────────────────────
    X_train, X_test, y_train, y_test, split_ts = time_split(X_clean, y, timestamps, test_size=0.2)

    print_section("시간순 분할 (ADR-002)")
    print(f"  분할 기준: {split_ts}")
    print(f"  Train: {len(y_train):,}행  |  불량 {y_train.sum()}개 ({y_train.mean()*100:.2f}%)")
    print(f"  Test:  {len(y_test):,}행  |  불량 {y_test.sum()}개 ({y_test.mean()*100:.2f}%)")
    print("  ※ stratify 없이 시간순 분할 → test셋 불량 비율이 train과 다를 수 있음 (의도된 설계)")

    # train 기준 클래스 비율 (XGB scale_pos_weight용)
    n_neg = (y_train == 0).sum()
    n_pos = (y_train == 1).sum()
    scale_pos = n_neg / n_pos
    print(f"\n  XGB scale_pos_weight (train 기준): {scale_pos:.2f}")

    # ── 4. Median imputation ──────────────────────────────────────────────────
    imputer = SimpleImputer(strategy="median")
    X_train_imp = imputer.fit_transform(X_train)
    X_test_imp  = imputer.transform(X_test)   # train median 적용 (누수 방지)

    # ── 5. Dummy 베이스라인 ───────────────────────────────────────────────────
    print_section("더미 베이스라인 (항상 양호=0 예측)")
    dummy = DummyClassifier(strategy="most_frequent")
    dummy.fit(X_train_imp, y_train)
    y_dummy      = dummy.predict(X_test_imp)
    y_dummy_prob = np.zeros(len(y_test))

    dummy_acc    = (y_dummy == y_test).mean()
    dummy_recall = ((y_dummy == 1) & (y_test == 1)).sum() / max((y_test == 1).sum(), 1)
    print(f"  Accuracy  : {dummy_acc:.4f}  ← 높아 보이지만 함정")
    print(f"  불량 Recall: {dummy_recall:.4f}  ← 불량을 하나도 못 잡음")
    print("  → Accuracy를 헤드라인 지표로 쓰면 안 되는 이유")

    # ── 6. Random Forest ──────────────────────────────────────────────────────
    print_section("Random Forest")
    rf = RandomForestClassifier(class_weight="balanced", random_state=RANDOM_STATE)
    rf.fit(X_train_imp, y_train)
    y_rf      = rf.predict(X_test_imp)
    y_rf_prob = rf.predict_proba(X_test_imp)[:, 1]
    print_metrics("Random Forest", y_test, y_rf, y_rf_prob)

    # ── 7. XGBoost ────────────────────────────────────────────────────────────
    print_section("XGBoost")
    xgb = XGBClassifier(
        scale_pos_weight=scale_pos,
        random_state=RANDOM_STATE,
        eval_metric="logloss",
        verbosity=0,
    )
    xgb.fit(X_train_imp, y_train)
    y_xgb      = xgb.predict(X_test_imp)
    y_xgb_prob = xgb.predict_proba(X_test_imp)[:, 1]
    print_metrics("XGBoost", y_test, y_xgb, y_xgb_prob)

    # ── 8. 비교 요약표 ────────────────────────────────────────────────────────
    print_section("비교 요약표")
    rows = [
        summary_row("Dummy (항상 양호)", y_test, y_dummy, y_dummy_prob),
        summary_row("Random Forest",     y_test, y_rf,    y_rf_prob),
        summary_row("XGBoost",           y_test, y_xgb,   y_xgb_prob),
    ]
    print(pd.DataFrame(rows).to_string(index=False))

    # ── 9. 해석 ───────────────────────────────────────────────────────────────
    rf_pr_auc  = average_precision_score(y_test, y_rf_prob)
    rf_recall  = recall_score(y_test, y_rf,  zero_division=0)
    rf_prec    = precision_score(y_test, y_rf, zero_division=0)
    xgb_pr_auc = average_precision_score(y_test, y_xgb_prob)
    xgb_recall = recall_score(y_test, y_xgb, zero_division=0)
    xgb_prec   = precision_score(y_test, y_xgb, zero_division=0)

    print_section("해석")
    print(f"""
SECOM 베이스라인 (시간순 분할, 피처 {X_clean.shape[1]}개):
  Random Forest — PR-AUC {rf_pr_auc:.3f}, Recall {rf_recall:.3f}, Precision {rf_prec:.3f}
  XGBoost       — PR-AUC {xgb_pr_auc:.3f}, Recall {xgb_recall:.3f}, Precision {xgb_prec:.3f}

AI4I 2020 대비 차이:
  - 1,567행 (AI4I 10,000행 대비 1/6) → 소규모 데이터, 과적합 위험 높음
  - test셋 불량 {y_test.sum()}개 (AI4I 68개 대비 훨씬 적음) → PR-AUC 분산 크게 나올 수 있음
  - 피처 {X_clean.shape[1]}개 (AI4I 6개) → 고차원, feature importance 해석 필요
  - 시간순 분할 → test 불량 비율 {y_test.mean()*100:.1f}% (train {y_train.mean()*100:.1f}% 와 다를 수 있음)

imputation 주의: train median을 test에 적용 (test→train 정보 누수 차단).
""")


if __name__ == "__main__":
    main()
