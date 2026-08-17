from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RESULTS_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "experiments"
    / "hybrid_policy_results.json"
)


def load_hybrid_results(path: Path = RESULTS_PATH) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"검증 결과가 없습니다: {path}. "
            "scripts/hybrid_policy_evaluation.py를 먼저 실행하세요."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def format_range(metric: dict[str, float]) -> str:
    median = metric["median"]
    minimum = metric["min"]
    maximum = metric["max"]

    def render(value: float) -> str:
        return str(int(value)) if float(value).is_integer() else f"{value:.1f}"

    return f"{render(median)} ({render(minimum)}–{render(maximum)})"


def comparison_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    summary = payload["summary"]
    run_count = len(payload["runs"])
    definitions = [
        ("통합 4모드 ML", "unified_ml"),
        ("HDF/PWF/OSF 모드별 ML", "sensor_ml"),
        ("HDF/PWF/OSF 물리 규칙", "physics_rule_baseline"),
        ("최종 하이브리드 정책", "hybrid_policy"),
    ]
    rows: list[dict[str, str]] = []
    for label, key in definitions:
        item = summary[key]
        count_key = "action_states" if key == "hybrid_policy" else "alerts"
        rows.append(
            {
                "비교 대상": label,
                "행동 대상 중앙값 (범위)": format_range(item[count_key]),
                "FN 중앙값 (범위)": format_range(item["false_negatives"]),
                "FN=0 반복": f"{item['zero_fn_runs']}/{run_count}",
            }
        )
    return rows
