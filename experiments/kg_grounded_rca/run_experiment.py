#!/usr/bin/env python3
"""Compare LLM-only RCA with knowledge-graph and SOP-grounded RCA.

The runner uses the current Codex ChatGPT OAuth session through ``codex exec``.
It does not require or read a model-provider API key.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCENARIO = """\
SCENARIO ID: twf-compound-001

Equipment: CNC-01
Component: spindle cutting tool T-17
Observed readings:
- tool_wear_min: 216 min (normal maximum: 200 min)
- torque_nm: 58 Nm (recent baseline: 42 Nm)
- rotational_speed_rpm: 1251 rpm
- air_temperature_k: 298.1 K
- process_temperature_k: 308.6 K

Observed symptoms:
- rising cutting torque during the last production cycle
- surface roughness outside the recent baseline

Task:
1. Identify the primary failure mode and most likely root cause.
2. Give a concise causal chain.
3. Produce a safe, ordered maintenance action plan.
4. Separate supported claims from uncertainties.

Do not use tools or inspect files. Return only JSON matching the supplied schema.
Write diagnosis and actions in Korean. Keep evidence IDs exactly as provided.
"""

GRAPH_AND_SOP = """\
AUTHORIZED KNOWLEDGE-GRAPH EVIDENCE:
- G1: CNC-01 -HAS_COMPONENT-> spindle
- G2: spindle -USES_TOOL-> tool-T17
- G3: tool-T17 -OBSERVED_BY-> tool_wear_min
- G4: tool_wear_min > 200 min -TRIGGERS-> TWF
- G5: TWF -CAUSED_BY-> tool_life_exceeded
- G6: TWF -CAN_LEAD_TO-> increased_cutting_resistance
- G7: increased_cutting_resistance -MANIFESTS_AS-> elevated_torque
- G8: TWF -MITIGATED_BY-> SOP-MNT-001

AUTHORIZED SOP EVIDENCE:
- S1: Wait for the current machining cycle to complete, then stop the CNC
  equipment immediately. Do not use the emergency stop button.
- S2: Remove the tool and visually inspect wear, breakage, or chipping. Measure
  actual wear with a tool presetter and discard the tool if it exceeds
  specification.
- S3: Install a conforming new tool, reset the tool length offset, and reset the
  tool life counter.
- S4: Perform one trial cut on scrap material, inspect at least three recently
  produced parts, and resume production only after supervisor approval.

Grounding rules:
- Treat only G1-G8 and S1-S4 as authoritative causal or procedural evidence.
- Every causal claim must cite one or more G IDs.
- Every maintenance action must cite one or more S IDs.
- Do not invent an edge, cause, procedure, or evidence ID.
- If the evidence is insufficient, record that in uncertainties.
"""

LLM_ONLY_RULES = """\
No knowledge graph or SOP evidence is available for this condition.
- Do not invent evidence IDs.
- Use an empty evidence_ids array for every claim and action.
- State any unverified causal or procedural assumption in uncertainties.
"""

VALID_EVIDENCE = {f"G{i}" for i in range(1, 9)} | {f"S{i}" for i in range(1, 5)}
FORBIDDEN_CAUSE_TERMS = (
    "bearing damage",
    "bearing failure",
    "lubrication failure",
    "coolant blockage",
    "electrical fault",
    "sensor calibration",
    "베어링 손상",
    "베어링 고장",
    "윤활 불량",
    "냉각수 막힘",
    "전기 고장",
    "센서 교정",
)
UNPROVIDED_PROCEDURE_TERMS = (
    "설비를 격리",
    "잔류 회전",
    "에너지가 제거",
    "holder",
    "collet",
    "runout",
    "홀더",
    "콜릿",
    "런아웃",
    "절삭유",
    "coolant",
    "칩 배출",
)


@dataclass(frozen=True)
class RunResult:
    condition: str
    repetition: int
    response: dict[str, Any]
    score: dict[str, Any]


def build_prompt(condition: str) -> str:
    evidence = GRAPH_AND_SOP if condition == "kg_sop" else LLM_ONLY_RULES
    return (
        "You are participating in a controlled RCA evaluation.\n\n"
        f"{SCENARIO}\n\n"
        f"{evidence}\n"
    )


def response_text(response: dict[str, Any]) -> str:
    diagnosis = response.get("diagnosis", {})
    causal_chain = [
        item.get("statement", "") if isinstance(item, dict) else item
        for item in diagnosis.get("causal_chain", [])
    ]
    pieces = [
        diagnosis.get("primary_failure_mode", ""),
        diagnosis.get("root_cause", ""),
        *causal_chain,
        *(item.get("action", "") for item in response.get("action_plan", [])),
        *(item.get("claim", "") for item in response.get("claims", [])),
        *response.get("uncertainties", []),
    ]
    return " ".join(str(piece) for piece in pieces).lower()


def has_any(text: str, alternatives: tuple[str, ...]) -> bool:
    return any(term.lower() in text for term in alternatives)


def score_response(condition: str, response: dict[str, Any]) -> dict[str, Any]:
    text = response_text(response)
    diagnosis = response.get("diagnosis", {})
    claims = response.get("claims", [])
    actions = response.get("action_plan", [])
    causal_chain = diagnosis.get("causal_chain", [])

    cited_ids = [
        evidence_id
        for item in [
            *claims,
            *actions,
            *(item for item in causal_chain if isinstance(item, dict)),
        ]
        for evidence_id in item.get("evidence_ids", [])
    ]
    invalid_ids = sorted({item for item in cited_ids if item not in VALID_EVIDENCE})
    unsupported_causes = sorted(
        term for term in FORBIDDEN_CAUSE_TERMS if term.lower() in text
    )
    unprovided_procedures = sorted(
        term for term in UNPROVIDED_PROCEDURE_TERMS if term.lower() in text
    )

    action_checks = {
        "controlled_stop": has_any(
            text,
            ("current cycle", "현재 사이클", "가공 사이클", "정상 정지"),
        ),
        "inspect_and_measure": (
            has_any(text, ("inspect", "inspection", "점검", "검사"))
            and has_any(text, ("measure", "presetter", "측정", "프리세터"))
        ),
        "replace_and_reset": (
            has_any(
                text,
                ("replace", "new tool", "교체", "신규 공구", "새 공구"),
            )
            and has_any(
                text,
                ("reset", "offset", "counter", "초기화", "보정값", "재설정"),
            )
        ),
        "trial_quality_approval": (
            has_any(
                text,
                ("trial", "scrap", "시운전", "시험 가공", "시험 절삭"),
            )
            and has_any(text, ("quality", "inspect", "품질", "검사"))
            and has_any(text, ("approval", "supervisor", "승인", "감독자"))
        ),
    }

    failure_mode_correct = has_any(
        diagnosis.get("primary_failure_mode", ""),
        ("TWF", "공구 마모 고장", "공구 마모", "과도한 마모"),
    )
    root_cause_correct = has_any(
        diagnosis.get("root_cause", ""),
        (
            "tool life",
            "tool wear",
            "life exceeded",
            "공구 수명",
            "공구 마모",
            "수명 초과",
            "공구 사용",
            "절삭날이 마모",
            "사용 시간이 정상 최대치",
            "정상 최대 사용시간",
            "사용시간이 정상 최대",
            "216분 사용",
        ),
    )

    if condition == "kg_sop":
        causal_chain_evidence_complete = bool(causal_chain) and all(
            (
                bool(item.get("evidence_ids"))
                and all(
                    evidence_id.startswith("G")
                    for evidence_id in item["evidence_ids"]
                )
            )
            if isinstance(item, dict)
            else bool(re.search(r"\bG[1-8]\b", item))
            for item in causal_chain
        )
        claim_evidence_complete = bool(claims) and all(
            item.get("evidence_ids")
            and all(evidence_id.startswith("G") for evidence_id in item["evidence_ids"])
            for item in claims
        )
        action_evidence_complete = bool(actions) and all(
            item.get("evidence_ids")
            and all(evidence_id.startswith("S") for evidence_id in item["evidence_ids"])
            for item in actions
        )
    else:
        causal_chain_evidence_complete = all(
            not item.get("evidence_ids")
            if isinstance(item, dict)
            else not re.search(r"\b[GS]\d+\b", item)
            for item in causal_chain
        )
        claim_evidence_complete = all(not item.get("evidence_ids") for item in claims)
        action_evidence_complete = all(not item.get("evidence_ids") for item in actions)

    checks = {
        "failure_mode_correct": failure_mode_correct,
        "root_cause_correct": root_cause_correct,
        "no_unsupported_causes": not unsupported_causes,
        "no_unprovided_procedures": not unprovided_procedures,
        "no_invalid_evidence_ids": not invalid_ids,
        "causal_chain_evidence_policy": causal_chain_evidence_complete,
        "claim_evidence_policy": claim_evidence_complete,
        "action_evidence_policy": action_evidence_complete,
        **action_checks,
    }

    return {
        "passed_checks": sum(bool(value) for value in checks.values()),
        "total_checks": len(checks),
        "pass_rate": round(
            sum(bool(value) for value in checks.values()) / len(checks),
            4,
        ),
        "checks": checks,
        "unsupported_causes": unsupported_causes,
        "unprovided_procedures": unprovided_procedures,
        "invalid_evidence_ids": invalid_ids,
        "claim_count": len(claims),
        "action_count": len(actions),
        "uncertainty_count": len(response.get("uncertainties", [])),
    }


def run_codex(
    codex_bin: str,
    schema_path: Path,
    condition: str,
    repetition: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="forgeai-kg-eval-") as temp_dir:
        output_path = Path(temp_dir) / "response.json"
        command = [
            codex_bin,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "-C",
            temp_dir,
            "-",
        ]
        completed = subprocess.run(
            command,
            input=build_prompt(condition),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"codex exec failed for {condition} repetition {repetition}: "
                f"{completed.stderr[-2000:]}"
            )
        return json.loads(output_path.read_text(encoding="utf-8"))


def summarize(results: list[RunResult]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for condition in ("llm_only", "kg_sop"):
        matching = [result for result in results if result.condition == condition]
        if not matching:
            continue
        summary[condition] = {
            "runs": len(matching),
            "mean_pass_rate": round(
                sum(item.score["pass_rate"] for item in matching) / len(matching),
                4,
            ),
            "failure_mode_accuracy": round(
                sum(item.score["checks"]["failure_mode_correct"] for item in matching)
                / len(matching),
                4,
            ),
            "root_cause_accuracy": round(
                sum(item.score["checks"]["root_cause_correct"] for item in matching)
                / len(matching),
                4,
            ),
            "unsupported_cause_runs": sum(
                bool(item.score["unsupported_causes"]) for item in matching
            ),
            "unprovided_procedure_runs": sum(
                bool(item.score["unprovided_procedures"]) for item in matching
            ),
            "evidence_policy_accuracy": round(
                sum(
                    item.score["checks"]["claim_evidence_policy"]
                    and item.score["checks"]["action_evidence_policy"]
                    for item in matching
                )
                / len(matching),
                4,
            ),
            "causal_chain_evidence_accuracy": round(
                sum(
                    item.score["checks"]["causal_chain_evidence_policy"]
                    for item in matching
                )
                / len(matching),
                4,
            ),
            "complete_action_plan_runs": sum(
                all(
                    item.score["checks"][name]
                    for name in (
                        "controlled_stop",
                        "inspect_and_measure",
                        "replace_and_reset",
                        "trial_quality_approval",
                    )
                )
                for item in matching
            ),
            "action_count_values": [
                item.score["action_count"] for item in matching
            ],
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "results",
    )
    args = parser.parse_args()

    schema_path = Path(__file__).resolve().parent / "response_schema.json"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.output_dir / timestamp
    run_dir.mkdir(parents=True, exist_ok=False)

    results: list[RunResult] = []
    for repetition in range(1, args.repetitions + 1):
        for condition in ("llm_only", "kg_sop"):
            response = run_codex(
                args.codex_bin,
                schema_path,
                condition,
                repetition,
            )
            score = score_response(condition, response)
            result = RunResult(condition, repetition, response, score)
            results.append(result)
            output = {
                "condition": condition,
                "repetition": repetition,
                "response": response,
                "score": score,
            }
            path = run_dir / f"{condition}-{repetition}.json"
            path.write_text(
                json.dumps(output, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(
                f"{condition} run={repetition} "
                f"pass_rate={score['pass_rate']:.2%}",
                flush=True,
            )

    report = {
        "experiment": "kg-grounded-rca",
        "scenario_id": "twf-compound-001",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repetitions_per_condition": args.repetitions,
        "summary": summarize(results),
        "limitations": [
            "One synthetic TWF scenario cannot establish general RCA effectiveness.",
            "Codex exec uses the currently authenticated default model; record the CLI "
            "configuration separately when strict model-version reproducibility is required.",
            "The deterministic scorer checks expected concepts and evidence policy, not "
            "semantic equivalence of every possible valid diagnosis.",
        ],
    }
    report_path = run_dir / "summary.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"results_dir={run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
