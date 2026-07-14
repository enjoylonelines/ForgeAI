"""
ML Predictor — AI4I XGBoost + Platt 보정 (ADR-013).

역할: rule_engine이 SAFE로 판정한 케이스 중 RNF(랜덤 고장)처럼
      단일 임계값으로 포착 불가능한 다변량 이상 패턴을 보조 탐지한다.
      rule_engine의 결과를 강등(DOWNGRADE)하지 않는다 — 상향(UPGRADE)만 허용.

ADR-003: 운영점 — threshold=0.30 (AI4I train set F1-최적점)
ADR-004: Platt scaling 보정 (sigmoid, cv=5)으로 XGBoost 확률 과신뢰 완화
ADR-013: EquipmentLog → float 인터페이스, 싱글턴 lazy train
"""
from __future__ import annotations

import functools
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import f1_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

from core.logging import get_logger
from models.equipment_log import EquipmentLog

_logger = get_logger(__name__)

_DATA_PATH = Path(__file__).parent.parent / "data" / "ai4i2020.csv"
_RANDOM_STATE = 42
_TYPE_MAP = {"L": 0, "M": 1, "H": 2}

# ADR-003: F1-최적 운영점. train set PR 곡선 분석으로 결정 (ablation 스크립트 검증).
ML_THRESHOLD: float = 0.30

_LEAK_COLS = ["TWF", "HDF", "PWF", "OSF", "RNF"]
_ID_COLS = ["UDI", "Product ID"]
_TARGET = "Machine failure"

# EquipmentLog sensor_id → AI4I CSV 컬럼명 ([] 제거 후)
_SENSOR_TO_COL: dict[str, str] = {
    "air_temperature_k":     "Air temperature K",
    "process_temperature_k": "Process temperature K",
    "rotational_speed_rpm":  "Rotational speed rpm",
    "torque_nm":             "Torque Nm",
    "tool_wear_min":         "Tool wear min",
}


@functools.lru_cache(maxsize=1)
def _get_model() -> tuple[CalibratedClassifierCV, list[str]]:
    """Lazy-train. 첫 호출 시 1회만 학습, 이후 캐시된 인스턴스 반환."""
    df = pd.read_csv(_DATA_PATH)
    df.columns = df.columns.str.replace(r"[\[\]<]", "", regex=True).str.strip()
    df["Type"] = df["Type"].map(_TYPE_MAP)

    X = df.drop(columns=_ID_COLS + _LEAK_COLS + [_TARGET])
    y = df[_TARGET]
    feature_cols = list(X.columns)

    X_tr, _, y_tr, _ = train_test_split(
        X.values, y.values, test_size=0.2, stratify=y.values, random_state=_RANDOM_STATE
    )

    n_neg = int((y_tr == 0).sum())
    n_pos = int((y_tr == 1).sum())

    base = XGBClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        scale_pos_weight=n_neg / n_pos,
        random_state=_RANDOM_STATE,
        eval_metric="logloss",
        verbosity=0,
    )
    # ADR-004: Platt scaling — 5-fold CV 보정으로 XGBoost 과신뢰 완화
    model = CalibratedClassifierCV(base, method="sigmoid", cv=5)
    model.fit(X_tr, y_tr)

    _logger.info({
        "event": "ml_predictor_trained",
        "features": feature_cols,
        "n_train": len(y_tr),
        "pos_ratio_pct": round(n_pos / len(y_tr) * 100, 2),
        "scale_pos_weight": round(n_neg / n_pos, 2),
    })
    return model, feature_cols


def predict_proba(log: EquipmentLog) -> float:
    """EquipmentLog → 보정된 고장 확률 [0, 1]."""
    model, feature_cols = _get_model()

    readings = {r.sensor_id: r.value for r in log.readings}
    machine_type = _TYPE_MAP.get(log.tags.get("type", "M").upper(), 1)

    row: list[float] = []
    for col in feature_cols:
        if col == "Type":
            row.append(float(machine_type))
        else:
            sensor_id = next((sid for sid, c in _SENSOR_TO_COL.items() if c == col), None)
            row.append(float(readings[sensor_id]) if sensor_id and sensor_id in readings else np.nan)

    X = np.array([row])
    return float(model.predict_proba(X)[0, 1])


def is_anomaly(log: EquipmentLog, threshold: float = ML_THRESHOLD) -> bool:
    """threshold 이상이면 이상 신호로 판정."""
    return predict_proba(log) >= threshold


def find_f1_optimal_threshold(y_true: np.ndarray, probas: np.ndarray) -> float:
    """PR 곡선에서 F1 최적 운영점을 반환한다 (ADR-003 근거 계산용)."""
    thresholds = np.arange(0.05, 0.95, 0.01)
    best_t, best_f1 = 0.5, 0.0
    for t in thresholds:
        preds = (probas >= t).astype(int)
        score = f1_score(y_true, preds, zero_division=0)
        if score > best_f1:
            best_f1, best_t = score, float(t)
    return best_t
