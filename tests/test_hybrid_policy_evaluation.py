from __future__ import annotations

import numpy as np

from scripts.hybrid_policy_evaluation import (
    DEFAULT_DATA,
    aggregate_runs,
    exact_rule_predictions,
    label_audit,
    load_dataset,
    run_seed,
    select_zero_fn_threshold,
    threshold_metrics,
)


def test_threshold_is_selected_from_validation_only() -> None:
    y_validation = np.array([0, 1, 0, 1])
    validation_proba = np.array([0.1, 0.7, 0.2, 0.4])

    threshold = select_zero_fn_threshold(y_validation, validation_proba)

    assert threshold == 0.4

    y_test = np.array([1, 0])
    test_proba = np.array([0.3, 0.2])
    metrics = threshold_metrics(y_test, test_proba, threshold)
    assert metrics.false_negatives == 1


def test_label_policy_matches_ai4i_audit_counts() -> None:
    df, _ = load_dataset(DEFAULT_DATA)

    audit = label_audit(df)

    assert audit["rows"] == 10_000
    assert audit["machine_failures"] == 339
    assert audit["primary_target_failures"] == 330
    assert audit["rnf_only_excluded"] == 18
    assert audit["flagless_failures_excluded"] == 9


def test_physics_rule_baseline_reproduces_deterministic_modes() -> None:
    df, _ = load_dataset(DEFAULT_DATA)
    predictions = exact_rule_predictions(df)

    for mode in ("HDF", "PWF", "OSF"):
        actual = df[mode].astype(bool).to_numpy()
        assert np.array_equal(predictions[mode], actual), mode


def test_final_hybrid_uses_rules_and_preventive_maintenance() -> None:
    df, features = load_dataset(DEFAULT_DATA)
    run = run_seed(df, features, seed=0)
    summary = aggregate_runs(df, [run])

    assert run["physics_rule_baseline"]["false_negatives"] == 0
    assert run["twf_maintenance"]["twf_failures_below_threshold"] == 0
    assert run["hybrid_policy"]["false_negatives"] == 0
    assert summary["hybrid_policy"]["zero_fn_runs"] == 1
