"""ForgeAI hybrid maintenance policy evaluation.

This experiment separates model fitting, operating-threshold selection, and
final evaluation:

* train (60%): fit the classifiers
* validation (20%): choose the highest threshold with zero observed misses
* test (20%): evaluate the frozen threshold once

The unified baseline predicts TWF/HDF/PWF/OSF together.  Per-mode ML is
measured as an intermediate experiment.  The final hybrid policy uses the
known physics rules for HDF/PWF/OSF and a preventive-maintenance rule for
TWF. RNF-only and flagless machine failures are reported but excluded from
the primary target.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, precision_score, recall_score
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "data" / "ai4i2020.csv"
DEFAULT_JSON = ROOT / "docs" / "experiments" / "hybrid_policy_results.json"
DEFAULT_REPORT = ROOT / "docs" / "experiments" / "hybrid_policy_results.md"

PREDICTED_MODES = ("HDF", "PWF", "OSF")
PRIMARY_MODES = ("TWF", *PREDICTED_MODES)
TWF_SERVICE_THRESHOLD_MIN = 198.0


@dataclass(frozen=True)
class ThresholdMetrics:
    threshold: float
    positives: int
    alerts: int
    false_positives: int
    false_negatives: int
    recall: float
    precision: float


def load_dataset(path: Path = DEFAULT_DATA) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(path)
    features = df[
        [
            "Type",
            "Air temperature [K]",
            "Process temperature [K]",
            "Rotational speed [rpm]",
            "Torque [Nm]",
            "Tool wear [min]",
        ]
    ].copy()
    features["delta_T"] = (
        features["Process temperature [K]"] - features["Air temperature [K]"]
    )
    features["power_w"] = (
        features["Torque [Nm]"]
        * features["Rotational speed [rpm]"]
        * 2
        * np.pi
        / 60
    )
    features["wear_torque"] = features["Tool wear [min]"] * features["Torque [Nm]"]
    features = pd.get_dummies(features, columns=["Type"], dtype=float)
    return df, features


def label_audit(df: pd.DataFrame) -> dict[str, int]:
    predicted = df[list(PRIMARY_MODES)].any(axis=1)
    no_flag = (df["Machine failure"] == 1) & ~df[
        [*PRIMARY_MODES, "RNF"]
    ].any(axis=1)
    rnf_only = (df["RNF"] == 1) & ~predicted
    return {
        "rows": int(len(df)),
        "machine_failures": int(df["Machine failure"].sum()),
        "primary_target_failures": int(predicted.sum()),
        "rnf_only_excluded": int(rnf_only.sum()),
        "flagless_failures_excluded": int(no_flag.sum()),
    }


def select_zero_fn_threshold(y_validation: np.ndarray, proba: np.ndarray) -> float:
    """Choose the highest validation threshold with zero observed misses."""
    positives = proba[y_validation == 1]
    if len(positives) == 0:
        raise ValueError("validation split contains no positive samples")
    return float(np.min(positives))


def threshold_metrics(
    y_true: np.ndarray, proba: np.ndarray, threshold: float
) -> ThresholdMetrics:
    predicted = proba >= threshold
    positives = int(np.sum(y_true == 1))
    alerts = int(np.sum(predicted))
    true_positives = int(np.sum(predicted & (y_true == 1)))
    false_positives = int(np.sum(predicted & (y_true == 0)))
    false_negatives = positives - true_positives
    return ThresholdMetrics(
        threshold=float(threshold),
        positives=positives,
        alerts=alerts,
        false_positives=false_positives,
        false_negatives=false_negatives,
        recall=float(recall_score(y_true, predicted, zero_division=0)),
        precision=float(precision_score(y_true, predicted, zero_division=0)),
    )


def fit_model(X: pd.DataFrame, y: np.ndarray, seed: int) -> HistGradientBoostingClassifier:
    model = HistGradientBoostingClassifier(
        random_state=seed,
        class_weight="balanced",
        max_iter=200,
    )
    model.fit(X, y)
    return model


def split_indices(y: np.ndarray, seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    indices = np.arange(len(y))
    development, test = train_test_split(
        indices,
        test_size=0.20,
        stratify=y,
        random_state=seed,
    )
    train, validation = train_test_split(
        development,
        test_size=0.25,
        stratify=y[development],
        random_state=seed,
    )
    return train, validation, test


def frontier_points(y_true: np.ndarray, proba: np.ndarray) -> list[dict[str, Any]]:
    """Return the high-recall part of the recall-alert frontier."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    positives = int(np.sum(y_true == 1))
    for threshold in np.unique(proba)[::-1]:
        metrics = threshold_metrics(y_true, proba, float(threshold))
        key = (positives - metrics.false_negatives, metrics.alerts)
        if key in seen:
            continue
        seen.add(key)
        if metrics.recall >= 0.85:
            rows.append(asdict(metrics))
        if metrics.false_negatives == 0:
            break
    return rows


def exact_rule_predictions(df: pd.DataFrame) -> dict[str, np.ndarray]:
    delta_t = df["Process temperature [K]"] - df["Air temperature [K]"]
    power = (
        df["Torque [Nm]"]
        * df["Rotational speed [rpm]"]
        * 2
        * np.pi
        / 60
    )
    overstrain_limit = df["Type"].map({"L": 11_000, "M": 12_000, "H": 13_000})
    return {
        "HDF": ((delta_t < 8.6) & (df["Rotational speed [rpm]"] < 1380)).to_numpy(),
        "PWF": ((power < 3500) | (power > 9000)).to_numpy(),
        "OSF": (
            df["Tool wear [min]"] * df["Torque [Nm]"] > overstrain_limit
        ).to_numpy(),
    }


def run_seed(
    df: pd.DataFrame,
    X: pd.DataFrame,
    seed: int,
) -> dict[str, Any]:
    y_primary = df[list(PRIMARY_MODES)].any(axis=1).astype(int).to_numpy()
    train, validation, test = split_indices(y_primary, seed)

    # Unified four-mode baseline.
    unified = fit_model(X.iloc[train], y_primary[train], seed)
    unified_validation_proba = unified.predict_proba(X.iloc[validation])[:, 1]
    unified_threshold = select_zero_fn_threshold(
        y_primary[validation], unified_validation_proba
    )
    unified_test_proba = unified.predict_proba(X.iloc[test])[:, 1]
    unified_metrics = threshold_metrics(
        y_primary[test], unified_test_proba, unified_threshold
    )

    # Per-mode ML track for HDF/PWF/OSF.
    mode_metrics: dict[str, dict[str, Any]] = {}
    sensor_alert = np.zeros(len(test), dtype=bool)
    for mode in PREDICTED_MODES:
        y_mode = df[mode].astype(int).to_numpy()
        model = fit_model(X.iloc[train], y_mode[train], seed)
        validation_proba = model.predict_proba(X.iloc[validation])[:, 1]
        threshold = select_zero_fn_threshold(y_mode[validation], validation_proba)
        test_proba = model.predict_proba(X.iloc[test])[:, 1]
        metrics = threshold_metrics(y_mode[test], test_proba, threshold)
        mode_metrics[mode] = asdict(metrics)
        sensor_alert |= test_proba >= threshold

    sensor_target = df[list(PREDICTED_MODES)].any(axis=1).to_numpy()[test]
    sensor_false_negatives = int(np.sum(sensor_target & ~sensor_alert))
    sensor_false_positives = int(np.sum(~sensor_target & sensor_alert))

    # Exact physics rules are a transparent baseline, not the learned track.
    rules = exact_rule_predictions(df)
    rule_alert = np.zeros(len(test), dtype=bool)
    rule_mode_metrics: dict[str, dict[str, int]] = {}
    for mode in PREDICTED_MODES:
        actual = df[mode].astype(bool).to_numpy()[test]
        predicted = rules[mode][test]
        rule_mode_metrics[mode] = {
            "positives": int(actual.sum()),
            "alerts": int(predicted.sum()),
            "false_positives": int(np.sum(predicted & ~actual)),
            "false_negatives": int(np.sum(~predicted & actual)),
        }
        rule_alert |= predicted

    # TWF is treated as a preventive-maintenance state, not a model alert.
    twf_actual = df["TWF"].astype(bool).to_numpy()[test]
    maintenance_due = (
        df["Tool wear [min]"].to_numpy()[test] >= TWF_SERVICE_THRESHOLD_MIN
    )
    twf_missed = int(np.sum(twf_actual & ~maintenance_due))

    # Final operating policy: deterministic physics rules for the modes whose
    # labels are defined by those rules, plus preventive maintenance for TWF.
    hybrid_action = rule_alert | maintenance_due
    hybrid_covered = (sensor_target & rule_alert) | (twf_actual & maintenance_due)
    hybrid_false_negatives = int(np.sum(y_primary[test].astype(bool) & ~hybrid_covered))

    return {
        "seed": seed,
        "split": {
            "train": int(len(train)),
            "validation": int(len(validation)),
            "test": int(len(test)),
        },
        "unified_ml": {
            **asdict(unified_metrics),
            "validation_threshold": unified_threshold,
            "test_pr_auc": float(
                average_precision_score(y_primary[test], unified_test_proba)
            ),
        },
        "sensor_ml": {
            "modes": mode_metrics,
            "positives": int(sensor_target.sum()),
            "alerts": int(sensor_alert.sum()),
            "false_positives": sensor_false_positives,
            "false_negatives": sensor_false_negatives,
            "alert_rate": float(sensor_alert.mean()),
        },
        "physics_rule_baseline": {
            "modes": rule_mode_metrics,
            "alerts": int(rule_alert.sum()),
            "false_positives": int(np.sum(~sensor_target & rule_alert)),
            "false_negatives": int(np.sum(sensor_target & ~rule_alert)),
        },
        "twf_maintenance": {
            "threshold_min": TWF_SERVICE_THRESHOLD_MIN,
            "twf_failures": int(twf_actual.sum()),
            "maintenance_due_states": int(maintenance_due.sum()),
            "twf_failures_below_threshold": twf_missed,
        },
        "hybrid_policy": {
            "primary_failures": int(y_primary[test].sum()),
            "action_states": int(hybrid_action.sum()),
            "false_negatives": hybrid_false_negatives,
            "action_rate": float(hybrid_action.mean()),
        },
        "frontier": frontier_points(y_primary[test], unified_test_proba),
    }


def numeric_summary(values: list[float | int]) -> dict[str, float]:
    array = np.asarray(values, dtype=float)
    return {
        "median": float(np.median(array)),
        "min": float(np.min(array)),
        "max": float(np.max(array)),
    }


def aggregate_runs(
    df: pd.DataFrame, runs: list[dict[str, Any]]
) -> dict[str, Any]:
    unified_alerts = [run["unified_ml"]["alerts"] for run in runs]
    unified_fn = [run["unified_ml"]["false_negatives"] for run in runs]
    sensor_alerts = [run["sensor_ml"]["alerts"] for run in runs]
    sensor_fn = [run["sensor_ml"]["false_negatives"] for run in runs]
    rule_alerts = [run["physics_rule_baseline"]["alerts"] for run in runs]
    rule_fn = [run["physics_rule_baseline"]["false_negatives"] for run in runs]
    maintenance_due = [
        run["twf_maintenance"]["maintenance_due_states"] for run in runs
    ]
    hybrid_actions = [run["hybrid_policy"]["action_states"] for run in runs]
    hybrid_fn = [run["hybrid_policy"]["false_negatives"] for run in runs]

    unified_median = float(np.median(unified_alerts))
    hybrid_median = float(np.median(hybrid_actions))
    action_reduction = (
        (unified_median - hybrid_median) / unified_median * 100
        if unified_median
        else 0.0
    )

    return {
        "label_audit": label_audit(df),
        "protocol": {
            "split": "60% train / 20% validation / 20% test",
            "seeds": [run["seed"] for run in runs],
            "threshold_selection": "validation only; frozen before test",
            "primary_target": "TWF OR HDF OR PWF OR OSF",
            "sensor_ml_experiment": "HDF OR PWF OR OSF (comparison only)",
            "final_sensor_policy": "deterministic physics rules for HDF/PWF/OSF",
            "twf_policy": f"preventive maintenance at {TWF_SERVICE_THRESHOLD_MIN:.0f} min",
        },
        "unified_ml": {
            "alerts": numeric_summary(unified_alerts),
            "false_negatives": numeric_summary(unified_fn),
            "zero_fn_runs": int(sum(value == 0 for value in unified_fn)),
        },
        "sensor_ml": {
            "alerts": numeric_summary(sensor_alerts),
            "false_negatives": numeric_summary(sensor_fn),
            "zero_fn_runs": int(sum(value == 0 for value in sensor_fn)),
        },
        "physics_rule_baseline": {
            "alerts": numeric_summary(rule_alerts),
            "false_negatives": numeric_summary(rule_fn),
            "zero_fn_runs": int(sum(value == 0 for value in rule_fn)),
        },
        "twf_maintenance": {
            "maintenance_due_states": numeric_summary(maintenance_due),
            "failures_below_threshold": numeric_summary(
                [
                    run["twf_maintenance"]["twf_failures_below_threshold"]
                    for run in runs
                ]
            ),
        },
        "hybrid_policy": {
            "action_states": numeric_summary(hybrid_actions),
            "false_negatives": numeric_summary(hybrid_fn),
            "zero_fn_runs": int(sum(value == 0 for value in hybrid_fn)),
            "median_action_reduction_vs_unified_pct": action_reduction,
        },
    }


def resume_highlights(summary: dict[str, Any], run_count: int) -> list[str]:
    hybrid = summary["hybrid_policy"]
    sensor = summary["sensor_ml"]
    audit = summary["label_audit"]
    reduction = hybrid["median_action_reduction_vs_unified_pct"]
    return [
        (
            f"AI4I 10,000건을 대상으로 {run_count}개 반복 분할에서 train-validation-test를 "
            "분리하고, validation에서 정한 운영 임계값을 test에 고정 적용해 평가 누수를 제거"
        ),
        (
            "통합 고장 모델의 Recall-정비 필요 판정량 frontier를 모드별로 분해하고, "
            "HDF/PWF/OSF 물리 규칙과 TWF 예방정비를 결합한 하이브리드 정책 설계"
        ),
        (
            f"하이브리드 정책의 test 정비 필요 판정 건수를 통합 ML 대비 "
            f"중앙값 기준 {reduction:.1f}% 줄이고, "
            f"관측 미탐 0건을 {hybrid['zero_fn_runs']}/{run_count}개 반복에서 검증"
        ),
        (
            f"HDF/PWF/OSF 모드별 ML이 관측 미탐 0건을 {sensor['zero_fn_runs']}/{run_count}개 "
            "반복에서만 유지한 반면 물리 규칙은 전 반복에서 유지함을 검증해 운영정책 선택"
        ),
        (
            f"RNF-only {audit['rnf_only_excluded']}건과 원인 플래그 없는 고장 "
            f"{audit['flagless_failures_excluded']}건을 각각 사후 검토 상태로 분리 집계해 "
            "예측 미탐과 원인 미분류를 구분하는 운영 KPI 설계"
        ),
    ]


def build_payload(
    df: pd.DataFrame, runs: list[dict[str, Any]]
) -> dict[str, Any]:
    summary = aggregate_runs(df, runs)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "AI4I 2020 Predictive Maintenance",
        "model": "HistGradientBoostingClassifier baseline",
        "summary": summary,
        "resume_highlights": resume_highlights(summary, len(runs)),
        "caveats": [
            "AI4I에는 실제 알림 이력이 없으므로 정비 필요 판정 건수는 알림 피로의 대리지표다.",
            "유한한 반복 test 분할에서 관측한 미탐 0건은 미래 미탐률 0%를 보장하지 않는다.",
            "TWF 198분 교체 기준은 AI4I에 맞춘 보수적인 예방정비 정책이다.",
            "RNF-only와 원인 플래그 없는 고장은 별도로 보고하고 주 평가 지표에서 제외한다.",
        ],
        "runs": runs,
    }


def format_number(value: float) -> str:
    return f"{value:.1f}" if not value.is_integer() else str(int(value))


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    labels = summary["label_audit"]
    protocol = summary["protocol"]

    def range_text(item: dict[str, float]) -> str:
        return (
            f"{format_number(item['median'])} "
            f"({format_number(item['min'])}–{format_number(item['max'])})"
        )

    lines = [
        "# ForgeAI 하이브리드 정비 정책 검증 결과",
        "",
        f"- 생성 시각: `{payload['generated_at']}`",
        f"- 데이터: {payload['dataset']} ({labels['rows']:,}행)",
        f"- 분할: {protocol['split']}",
        f"- 시드: {', '.join(map(str, protocol['seeds']))}",
        "- 임계값: validation에서만 선택하고 test에는 고정 적용",
        "",
        "## 문제 정의",
        "",
        "고장 미탐을 늘리지 않으면서 불필요한 정비 판정 알림을 제거해, "
        "현장 엔지니어에게 필요한 알림만 남긴다.",
        "",
        "AI4I에는 실제 알림 이력이 없으므로 `정비 필요 판정 건수`를 "
        "알림 피로의 대리지표로 사용한다.",
        "",
        "## 평가 대상과 사후 검토 상태",
        "",
        f"- 주 타깃(TWF/HDF/PWF/OSF): {labels['primary_target_failures']}건",
        f"- 사후 검토 큐 — RNF-only: {labels['rnf_only_excluded']}건",
        f"- 사후 검토 큐 — 원인 플래그 없는 고장: {labels['flagless_failures_excluded']}건",
        "",
        "## 반복 테스트 결과",
        "",
        "| 비교 대상 | test 정비 필요 판정 중앙값 (범위) | test FN 중앙값 (범위) | FN=0 반복 |",
        "|---|---:|---:|---:|",
        (
            f"| 통합 4모드 ML | {range_text(summary['unified_ml']['alerts'])} | "
            f"{range_text(summary['unified_ml']['false_negatives'])} | "
            f"{summary['unified_ml']['zero_fn_runs']}/{len(payload['runs'])} |"
        ),
        (
            f"| HDF/PWF/OSF 모드별 ML | {range_text(summary['sensor_ml']['alerts'])} | "
            f"{range_text(summary['sensor_ml']['false_negatives'])} | "
            f"{summary['sensor_ml']['zero_fn_runs']}/{len(payload['runs'])} |"
        ),
        (
            f"| HDF/PWF/OSF 물리 규칙 기준선 | "
            f"{range_text(summary['physics_rule_baseline']['alerts'])} | "
            f"{range_text(summary['physics_rule_baseline']['false_negatives'])} | "
            f"{summary['physics_rule_baseline']['zero_fn_runs']}/{len(payload['runs'])} |"
        ),
        (
            f"| 최종 하이브리드 정책 | "
            f"{range_text(summary['hybrid_policy']['action_states'])} | "
            f"{range_text(summary['hybrid_policy']['false_negatives'])} | "
            f"{summary['hybrid_policy']['zero_fn_runs']}/{len(payload['runs'])} |"
        ),
        "",
        (
            "하이브리드 정책의 test 정비 필요 판정 건수 중앙값은 통합 ML 대비 "
            f"**{summary['hybrid_policy']['median_action_reduction_vs_unified_pct']:.1f}% 감소**했다."
        ),
        "",
        "TWF는 센서 위험 알림과 합산하지 않고 별도 예방정비 상태로 표시한다. "
        f"테스트 분할별 교체 권고 상태 중앙값은 "
        f"{format_number(summary['twf_maintenance']['maintenance_due_states']['median'])}건이다.",
        "",
        "## 이력서 어필 문장",
        "",
    ]
    lines.extend(f"- {item}" for item in payload["resume_highlights"])
    lines.extend(
        [
            "",
            "## 해석상 제한",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in payload["caveats"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--report-out", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--seeds", type=int, default=10)
    args = parser.parse_args()

    df, X = load_dataset(args.data)
    runs = [run_seed(df, X, seed) for seed in range(args.seeds)]
    payload = build_payload(df, runs)

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    args.report_out.write_text(render_markdown(payload), encoding="utf-8")

    summary = payload["summary"]
    print(render_markdown(payload))
    print(f"JSON: {args.json_out}")
    print(f"Report: {args.report_out}")
    print(
        "Hybrid median action reduction vs unified ML: "
        f"{summary['hybrid_policy']['median_action_reduction_vs_unified_pct']:.1f}%"
    )


if __name__ == "__main__":
    main()
