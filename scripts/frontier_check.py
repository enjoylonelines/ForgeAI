"""Recall–알림량 frontier 검증: 미탐 0 제약 하 최소 알림 임계값 탐색.

- 타겟: TWF|HDF|PWF|OSF (RNF 및 플래그 없는 machine failure 행은 별도 집계)
- 모델: HistGradientBoosting (baseline)
- 출력: frontier 주요 지점 + FN=0 달성 임계값의 알림량, 시드별 변동
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import train_test_split

DATA = "data/ai4i2020.csv"
MODES = ["TWF", "HDF", "PWF", "OSF"]


def load():
    df = pd.read_csv(DATA)
    df["target"] = (df[MODES].sum(axis=1) > 0).astype(int)

    # 라벨 특이 케이스 집계
    no_flag = df[(df["Machine failure"] == 1) & (df[MODES + ["RNF"]].sum(axis=1) == 0)]
    rnf_only = df[(df["RNF"] == 1) & (df[MODES].sum(axis=1) == 0)]
    print(f"전체 {len(df)}행 | 타겟(4모드) 고장 {df['target'].sum()}건")
    print(f"machine failure=1인데 플래그 전부 0: {len(no_flag)}행 (타겟에서 제외됨)")
    print(f"RNF 단독: {len(rnf_only)}행 (타겟에서 제외됨)\n")

    df["delta_T"] = df["Process temperature [K]"] - df["Air temperature [K]"]
    df["power"] = df["Torque [Nm]"] * df["Rotational speed [rpm]"] * 2 * np.pi / 60
    X = pd.get_dummies(
        df[["Type", "Air temperature [K]", "Process temperature [K]",
            "Rotational speed [rpm]", "Torque [Nm]", "Tool wear [min]",
            "delta_T", "power"]],
        columns=["Type"],
    )
    return X, df["target"].values, df


def frontier(y_true, proba):
    """임계값 스윕 → (threshold, recall, alerts, FP) 목록."""
    order = np.argsort(-proba)
    rows = []
    for th in np.unique(proba)[::-1]:
        pred = proba >= th
        tp = int((pred & (y_true == 1)).sum())
        fp = int((pred & (y_true == 0)).sum())
        fn = int(y_true.sum()) - tp
        rows.append((th, tp / y_true.sum(), tp + fp, fp, fn))
    return rows


def run(seed):
    X, y, _ = load() if seed == 0 else (_X, _y, None)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, stratify=y, random_state=seed)
    clf = HistGradientBoostingClassifier(random_state=seed, class_weight="balanced")
    clf.fit(Xtr, ytr)
    proba = clf.predict_proba(Xte)[:, 1]
    return yte, proba, len(Xte)


if __name__ == "__main__":
    _X, _y, _df = load()

    # ── 대표 시드로 frontier 출력 ──
    yte, proba, n_test = run(0)
    rows = frontier(yte, proba)
    n_fail = int(yte.sum())
    print(f"[seed 0] 테스트 {n_test}행, 고장 {n_fail}건")
    print(f"{'recall':>7} {'미탐':>4} {'알림수':>5} {'오알림(FP)':>8} {'알림률':>7}")
    shown = set()
    for th, rec, alerts, fp, fn in rows:
        key = round(rec, 3)
        if key in shown:
            continue
        if rec >= 0.85 or fn == 0:
            shown.add(key)
            print(f"{rec:7.3f} {fn:4d} {alerts:5d} {fp:8d} {alerts/n_test:6.1%}")
        if fn == 0:
            break

    # ── FN=0 지점의 시드별 변동 ──
    print("\n[FN=0 제약 하 최소 알림] 시드별:")
    for seed in range(5):
        yte, proba, n_test = run(seed)
        rows = frontier(yte, proba)
        for th, rec, alerts, fp, fn in rows:
            if fn == 0:
                print(f"  seed {seed}: 임계값 {th:.4f} → 알림 {alerts}건 "
                      f"(FP {fp}, 알림률 {alerts/n_test:.1%}, 고장 {int(yte.sum())}건 전부 검출)")
                break
