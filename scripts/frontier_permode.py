"""개선 실험: 모드별 이진 모델 + 물리 피처 → FN=0 알림 비용을 모드별로 분해.

가설: HDF/PWF/OSF는 결정론적 생성 조건이라 거의 완벽 분리 가능,
FN=0의 알림 비용 대부분은 확률적 TWF에서 나온다.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import train_test_split

DATA = "data/ai4i2020.csv"
MODES = ["TWF", "HDF", "PWF", "OSF"]


def load():
    df = pd.read_csv(DATA)
    df["delta_T"] = df["Process temperature [K]"] - df["Air temperature [K]"]
    df["power"] = df["Torque [Nm]"] * df["Rotational speed [rpm]"] * 2 * np.pi / 60
    df["wear_torque"] = df["Tool wear [min]"] * df["Torque [Nm]"]
    X = pd.get_dummies(
        df[["Type", "Air temperature [K]", "Process temperature [K]",
            "Rotational speed [rpm]", "Torque [Nm]", "Tool wear [min]",
            "delta_T", "power", "wear_torque"]],
        columns=["Type"],
    )
    y_any = (df[MODES].sum(axis=1) > 0).astype(int).values
    return X, df, y_any


def fn0_alerts(y_true, proba):
    """FN=0을 만족하는 최대 임계값에서의 알림 수."""
    if y_true.sum() == 0:
        return 0, 0
    th = proba[y_true == 1].min()
    pred = proba >= th
    return int(pred.sum()), int((pred & (y_true == 0)).sum())


if __name__ == "__main__":
    X, df, y_any = load()

    agg = {m: [] for m in MODES}
    agg_comb, agg_base = [], []

    for seed in range(5):
        idx_tr, idx_te = train_test_split(
            np.arange(len(X)), test_size=0.2, stratify=y_any, random_state=seed)
        Xtr, Xte = X.iloc[idx_tr], X.iloc[idx_te]

        # 베이스라인: 통합 타겟 단일 모델
        clf = HistGradientBoostingClassifier(random_state=seed, class_weight="balanced")
        clf.fit(Xtr, y_any[idx_tr])
        a, f = fn0_alerts(y_any[idx_te], clf.predict_proba(Xte)[:, 1])
        agg_base.append(a)

        # 모드별 이진 모델
        probas = {}
        for m in MODES:
            ym = df[m].values
            cm = HistGradientBoostingClassifier(random_state=seed, class_weight="balanced")
            cm.fit(Xtr, ym[idx_tr])
            p = cm.predict_proba(Xte)[:, 1]
            probas[m] = p
            a, f = fn0_alerts(ym[idx_te], p)
            agg[m].append((a, int(ym[idx_te].sum())))

        # 통합: 모드별 FN=0 임계값을 각각 걸고 OR 결합
        alert = np.zeros(len(Xte), dtype=bool)
        for m in MODES:
            ym = df[m].values[idx_te]
            if ym.sum() == 0:
                continue
            th = probas[m][ym == 1].min()
            alert |= probas[m] >= th
        miss = int((y_any[idx_te] == 1).sum() - (alert & (y_any[idx_te] == 1)).sum())
        agg_comb.append((int(alert.sum()), miss))

    n_te = len(idx_te)
    print(f"테스트 {n_te}행 기준, 시드 5개\n")
    print("[모드별 FN=0 알림 비용] (해당 모드 고장 전부 검출에 필요한 알림 수)")
    for m in MODES:
        alerts = [a for a, _ in agg[m]]
        fails = [f for _, f in agg[m]]
        print(f"  {m}: 고장 {np.mean(fails):4.1f}건 → 알림 중앙값 {int(np.median(alerts)):4d}건 "
              f"(min {min(alerts)}, max {max(alerts)})")
    print(f"\n[통합 비교] 미탐 0 기준 알림 수 (시드 5개 중앙값)")
    print(f"  베이스라인(단일 모델):      {int(np.median(agg_base)):4d}건 (min {min(agg_base)}, max {max(agg_base)})")
    comb_alerts = [a for a, _ in agg_comb]
    comb_miss = [m_ for _, m_ in agg_comb]
    print(f"  모드별 OR 결합:             {int(np.median(comb_alerts)):4d}건 (min {min(comb_alerts)}, max {max(comb_alerts)}, 미탐 {sum(comb_miss)}건)")
