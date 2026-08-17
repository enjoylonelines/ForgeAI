from __future__ import annotations

from streamlit.testing.v1 import AppTest

from dashboard.hybrid_results import (
    RESULTS_PATH,
    comparison_rows,
    format_range,
    load_hybrid_results,
)


def test_generated_results_are_available_to_dashboard() -> None:
    payload = load_hybrid_results(RESULTS_PATH)

    assert payload["summary"]["hybrid_policy"]["zero_fn_runs"] == 10
    assert (
        payload["summary"]["hybrid_policy"][
            "median_action_reduction_vs_unified_pct"
        ]
        > 0
    )


def test_comparison_rows_include_final_policy() -> None:
    payload = load_hybrid_results(RESULTS_PATH)

    rows = comparison_rows(payload)

    assert len(rows) == 4
    assert rows[-1]["비교 대상"] == "최종 하이브리드 정책"
    assert rows[-1]["FN=0 반복"] == "10/10"


def test_format_range_keeps_median_and_spread() -> None:
    assert format_range({"median": 213.0, "min": 196.0, "max": 224.0}) == (
        "213 (196–224)"
    )


def test_dashboard_home_renders_verified_portfolio_metrics() -> None:
    app = AppTest.from_file("dashboard/app.py", default_timeout=15).run()

    assert not app.exception
    assert app.title[0].value == "ForgeAI 하이브리드 설비 모니터링"
    assert [(metric.label, metric.value) for metric in app.metric[:4]] == [
        ("행동 대상 감소", "70.9%"),
        ("관측 미탐 0", "10/10회"),
        ("최종 행동 대상", "213건"),
        ("평가 프로토콜", "60/20/20"),
    ]
    assert [(metric.label, metric.value) for metric in app.metric[6:8]] == [
        ("RNF-only 검토", "18건"),
        ("원인 플래그 없음", "9건"),
    ]


def test_hybrid_results_page_renders_comparison_and_label_audit() -> None:
    app = AppTest.from_file(
        "dashboard/pages/04_hybrid_results.py",
        default_timeout=15,
    ).run()

    assert not app.exception
    assert app.title[0].value == "하이브리드 정비 정책 검증"
    assert [(metric.label, metric.value) for metric in app.metric[:4]] == [
        ("행동 대상 감소", "70.9%"),
        ("하이브리드 FN=0", "10/10회"),
        ("최종 행동 대상", "213건"),
        ("주 평가 고장", "330건"),
    ]
    assert [(metric.label, metric.value) for metric in app.metric[6:8]] == [
        ("RNF-only", "18건"),
        ("원인 플래그 없음", "9건"),
    ]
    assert len(app.dataframe) == 1
    assert len(app.get("plotly_chart")) == 1
