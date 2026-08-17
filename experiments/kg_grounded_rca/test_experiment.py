from __future__ import annotations

from run_experiment import score_response, summarize, RunResult


def _base_response() -> dict:
    return {
        "scenario_id": "twf-compound-001",
        "diagnosis": {
            "primary_failure_mode": "공구 마모 고장(TWF)",
            "root_cause": "공구 수명 초과",
            "causal_chain": [
                {"statement": "마모 한계 초과가 TWF를 유발한다.", "evidence_ids": ["G4"]},
                {"statement": "TWF가 절삭 저항을 증가시킨다.", "evidence_ids": ["G6"]},
            ],
            "confidence": 0.9,
        },
        "action_plan": [
            {
                "step_number": 1,
                "action": "현재 가공 사이클 완료 후 정상 정지한다.",
                "evidence_ids": ["S1"],
            },
            {
                "step_number": 2,
                "action": "공구를 검사하고 프리세터로 측정한다.",
                "evidence_ids": ["S2"],
            },
            {
                "step_number": 3,
                "action": "새 공구로 교체하고 오프셋을 재설정한다.",
                "evidence_ids": ["S3"],
            },
            {
                "step_number": 4,
                "action": "시험 절삭 후 품질 검사하고 감독자 승인 후 재개한다.",
                "evidence_ids": ["S4"],
            },
        ],
        "claims": [
            {"claim": "마모 한계 초과가 TWF를 유발한다.", "evidence_ids": ["G4"]},
            {"claim": "TWF가 절삭 저항을 증가시킨다.", "evidence_ids": ["G6"]},
        ],
        "uncertainties": [],
    }


def test_grounded_response_passes_all_policies() -> None:
    score = score_response("kg_sop", _base_response())

    assert score["pass_rate"] == 1.0
    assert score["checks"]["causal_chain_evidence_policy"] is True
    assert score["checks"]["action_evidence_policy"] is True


def test_free_form_chain_without_graph_ids_fails_provenance_policy() -> None:
    response = _base_response()
    response["diagnosis"]["causal_chain"] = [
        "마모 한계 초과가 TWF를 유발한다.",
        "TWF가 절삭 저항을 증가시킨다.",
    ]

    score = score_response("kg_sop", response)

    assert score["checks"]["causal_chain_evidence_policy"] is False


def test_summary_counts_unprovided_procedure_runs() -> None:
    response = _base_response()
    response["action_plan"][1]["action"] += " 절삭유와 홀더도 점검한다."
    score = score_response("kg_sop", response)
    result = RunResult("kg_sop", 1, response, score)

    summary = summarize([result])

    assert summary["kg_sop"]["unprovided_procedure_runs"] == 1
