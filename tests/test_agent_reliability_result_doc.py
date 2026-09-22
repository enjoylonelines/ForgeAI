from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "docs" / "agent-reliability-result.md"
RESULT_JSON = ROOT / "output" / "agent_reliability_mock.json"
LIVE_RESULT_JSON = ROOT / "output" / "agent_reliability_live_api.json"
README = ROOT / "README.md"


def _summary() -> dict:
    return json.loads(RESULT_JSON.read_text(encoding="utf-8"))["summary"]


def test_agent_reliability_result_matches_json_metrics():
    text = REPORT.read_text(encoding="utf-8")
    summary = _summary()
    metrics = summary["metrics"]
    generated_at = json.loads(RESULT_JSON.read_text(encoding="utf-8"))["generated_at"]

    expected_snippets = [
        f"Generated at: `{generated_at}`",
        f"Total cases | {summary['total_cases']}",
        f"Evaluated cases | {summary['evaluated_cases']}",
        f"Skipped live opt-in cases | {summary['skipped_cases']}",
        f"Exact tool-set accuracy | {metrics['exact_tool_set_accuracy_pct']}%",
        f"Required-tool recall | {metrics['required_tool_recall_pct']}%",
        f"Forbidden-tool call rate | {metrics['forbidden_tool_call_rate_pct']}%",
        f"Invalid-argument rejection rate | {metrics['invalid_argument_rejection_rate_pct']}%",
        f"Max-iteration compliance | {metrics['max_iteration_compliance_pct']}%",
        f"Route accuracy | {metrics['route_accuracy_pct']}%",
        f"Unsafe AUTO count | {metrics['unsafe_auto_count']}",
    ]

    for snippet in expected_snippets:
        assert snippet in text


def test_readme_links_agent_reliability_result():
    text = README.read_text(encoding="utf-8")

    assert "docs/agent-reliability-result.md" in text
    assert "에이전트 신뢰성 검증" in text
    assert "기대한 라우팅 결과와 실제 결과가\n모두 일치" in text
    assert "필요한 도구 호출 누락은 없었" in text
    assert "자동 처리로\n넘어간 경우는 0건" in text
    assert "실제 LLM 성능 벤치마크가 아니라" in text
    assert "1회 선택 실행 확인" in text
    assert "운영 SLA" in text
    assert "전체 ForgePipeline 실시간 벤치마크" in text
    assert "`unavailable`" in text


def test_agent_reliability_result_matches_live_api_smoke_json():
    text = REPORT.read_text(encoding="utf-8")
    live = json.loads(LIVE_RESULT_JSON.read_text(encoding="utf-8"))
    result = live["result"]
    observability = live["observability"]
    usage = observability["token_usage"]
    cost = observability["monetary_cost"]

    assert "output/agent_reliability_live_api.json" in text
    assert f"status: `{result['status']}`" in text
    assert f"latency ms: `{observability['latency']['latency_ms']}`" in text
    assert f"prompt tokens: {usage['prompt_tokens']}" in text
    assert f"completion tokens: {usage['completion_tokens']}" in text
    assert f"total tokens: {usage['total_tokens']}" in text
    assert f"status: `{cost['status']}`" in text
    assert "live_api | `observed`, not thresholded | `observed` | `unavailable`" in text
    assert "XGBoost segfault" not in text
    assert "Pipeline orchestration 테스트는 `ml_predictor.predict_proba`를 mock 처리" in text
    assert "Result: `4 passed, 1 deselected`" in text
    assert "Result: `1 passed, 4 deselected`" in text
    assert "포트폴리오용 한국어 표현" in text
    assert "기대 라우팅 일치율 100.0%" in text
    assert "필수 도구 호출 충족률 100.0%" in text
    assert "위험 상황 자동 처리 0건" in text
    assert "실제 LLM 성능 벤치마크가 아니라" in text


def test_agent_reliability_contract_points_to_current_evidence():
    contract = ROOT / "docs" / "agent-reliability-evaluation.md"
    text = contract.read_text(encoding="utf-8")

    assert "scripts/eval_agent_reliability.py" in text
    assert "output/agent_reliability_mock.json" in text
    assert "output/agent_reliability_live_api.json" in text
    assert "This U2 contract does not implement" not in text
    assert "not a full ForgePipeline live benchmark" in text
    assert "Monetary cost remains `unavailable`" in text
