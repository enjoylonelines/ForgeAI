#!/usr/bin/env python3
"""Compare single-label and multi-path grounding for a TWF+OSF event."""

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


CONDITIONS = ("llm_only", "single_label_osf", "multi_path_kg_sop")

SCENARIO = """\
SCENARIO ID: twf-osf-compound-001

Equipment: CNC-02
Machine type: M (Medium)
Component: spindle cutting tool T-21
Observed readings:
- tool_wear_min: 216 min
- torque_nm: 58 Nm
- rotational_speed_rpm: 1450 rpm
- air_temperature_k: 298.1 K
- process_temperature_k: 308.6 K
- computed tool_wear × torque: 12,528 min·Nm

Known operating boundaries:
- tool wear warning/replacement boundary: 200 min
- M-type overstrain boundary: 12,000 min·Nm

Observed symptoms:
- cutting torque rose during the last production cycle
- chatter marks appeared on the workpiece

Task:
1. Identify the primary safety-priority failure mode.
2. Identify every contributing failure mode supported by the input or evidence.
3. Explain how the failure modes interact.
4. Produce a safe, ordered maintenance action plan.
5. Separate supported claims from uncertainties.

Do not use tools or inspect files. Return only JSON matching the supplied schema.
Write diagnosis and actions in Korean. Keep evidence IDs exactly as provided.
"""

LLM_ONLY = """\
No knowledge graph or approved SOP evidence is available.
- Do not invent evidence IDs.
- Every evidence_ids array must be empty.
- Put unverified causal and procedural assumptions in uncertainties.
"""

SINGLE_LABEL_OSF = """\
AUTHORIZED SINGLE-LABEL GRAPH EVIDENCE:
- G1: CNC-02 -HAS_COMPONENT-> spindle
- G2: spindle -USES_TOOL-> tool-T21
- G3: tool_wear × torque > 12,000 min·Nm -TRIGGERS-> OSF
- G4: OSF -CAUSED_BY-> combined_mechanical_overstrain
- G5: OSF -MITIGATED_BY-> SOP-MNT-004

AUTHORIZED OSF SOP EVIDENCE:
- O1: Use Feed Hold immediately, keep the spindle rotating, move the tool to a
  safe position, and then stop the spindle.
- O2: Inspect tool breakage, the torque sensor, spindle runout, workpiece clamp,
  feed axes, and ballscrews for damage or abnormal play.
- O3: Review feed, speed, and depth of cut. Reduce feed by 15-25% in high-torque
  sections and review whether tool-life settings should be shortened.
- O4: Install a new tool and reset its offset.
- O5: Verify the program path with a dry run, then perform a trial cut at 30%
  feed override before gradually returning to normal speed.

Grounding rules:
- Only G1-G5 and O1-O5 are authoritative.
- Every causal-chain item and causal claim must cite G IDs.
- Every action must cite O IDs.
- Do not infer a second failure mode unless this evidence directly supports it.
- Put missing causal context in uncertainties.
"""

MULTI_PATH_KG_SOP = """\
AUTHORIZED MULTI-PATH GRAPH EVIDENCE:
- G1: CNC-02 -HAS_COMPONENT-> spindle
- G2: spindle -USES_TOOL-> tool-T21
- G3: tool_wear × torque > 12,000 min·Nm -TRIGGERS-> OSF
- G4: OSF -CAUSED_BY-> combined_mechanical_overstrain
- G5: OSF -MITIGATED_BY-> SOP-MNT-004
- G6: tool_wear_min > 200 min -TRIGGERS-> TWF
- G7: TWF -CAUSED_BY-> tool_life_exceeded
- G8: TWF -CAN_LEAD_TO-> increased_cutting_resistance
- G9: increased_cutting_resistance -CONTRIBUTES_TO-> combined_mechanical_overstrain
- G10: TWF -MITIGATED_BY-> SOP-MNT-001

AUTHORIZED OSF SOP EVIDENCE:
- O1: Use Feed Hold immediately, keep the spindle rotating, move the tool to a
  safe position, and then stop the spindle.
- O2: Inspect tool breakage, the torque sensor, spindle runout, workpiece clamp,
  feed axes, and ballscrews for damage or abnormal play.
- O3: Review feed, speed, and depth of cut. Reduce feed by 15-25% in high-torque
  sections and review whether tool-life settings should be shortened.
- O4: Install a new tool and reset its offset.
- O5: Verify the program path with a dry run, then perform a trial cut at 30%
  feed override before gradually returning to normal speed.

AUTHORIZED TWF SOP EVIDENCE:
- T1: Remove the tool, visually inspect wear, breakage, or chipping, and measure
  actual wear with a tool presetter.
- T2: Install a conforming new tool, reset the tool length offset, and reset the
  tool-life counter.
- T3: Perform a trial cut on scrap material and inspect at least three recently
  produced parts.
- T4: Resume production only after supervisor approval.

Grounding rules:
- Only G1-G10, O1-O5, and T1-T4 are authoritative.
- OSF is the primary safety-priority mode; preserve TWF as a contributor.
- Every causal-chain item and causal claim must cite G IDs.
- Every action must cite O or T IDs.
- The final plan must cover both OSF damage risk and TWF tool-life remediation.
- Do not invent an edge, procedure, or evidence ID.
"""

CONTEXTS = {
    "llm_only": LLM_ONLY,
    "single_label_osf": SINGLE_LABEL_OSF,
    "multi_path_kg_sop": MULTI_PATH_KG_SOP,
}

VALID_IDS = {
    "llm_only": set(),
    "single_label_osf": {f"G{i}" for i in range(1, 6)}
    | {f"O{i}" for i in range(1, 6)},
    "multi_path_kg_sop": {f"G{i}" for i in range(1, 11)}
    | {f"O{i}" for i in range(1, 6)}
    | {f"T{i}" for i in range(1, 5)},
}

UNPROVIDED_PROCEDURES = (
    "coolant",
    "lubrication",
    "electrical",
    "sensor calibration",
    "절삭유",
    "윤활",
    "전기 계통",
    "센서 교정",
    "비상 정지",
    "emergency stop",
)


@dataclass(frozen=True)
class RunResult:
    condition: str
    repetition: int
    response: dict[str, Any]
    score: dict[str, Any]


def build_prompt(condition: str) -> str:
    return (
        "You are participating in a controlled compound-failure RCA evaluation.\n\n"
        f"{SCENARIO}\n\n"
        f"{CONTEXTS[condition]}\n"
    )


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _diagnosis_text(response: dict[str, Any]) -> str:
    diagnosis = response.get("diagnosis", {})
    pieces = [
        diagnosis.get("primary_failure_mode", ""),
        *diagnosis.get("contributing_failure_modes", []),
        diagnosis.get("root_cause", ""),
        *(
            item.get("statement", "") if isinstance(item, dict) else str(item)
            for item in diagnosis.get("causal_chain", [])
        ),
        *(item.get("claim", "") for item in response.get("claims", [])),
    ]
    return " ".join(str(piece) for piece in pieces)


def _action_text(response: dict[str, Any]) -> str:
    return " ".join(
        str(item.get("action", ""))
        for item in response.get("action_plan", [])
    )


def _all_evidence_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    diagnosis = response.get("diagnosis", {})
    chain = [
        item
        for item in diagnosis.get("causal_chain", [])
        if isinstance(item, dict)
    ]
    return [*chain, *response.get("claims", []), *response.get("action_plan", [])]


def score_response(condition: str, response: dict[str, Any]) -> dict[str, Any]:
    diagnosis = response.get("diagnosis", {})
    diagnosis_text = _diagnosis_text(response)
    action_text = _action_text(response)
    chain = diagnosis.get("causal_chain", [])
    claims = response.get("claims", [])
    actions = response.get("action_plan", [])
    contributors = " ".join(diagnosis.get("contributing_failure_modes", []))

    cited_ids = [
        evidence_id
        for item in _all_evidence_items(response)
        for evidence_id in item.get("evidence_ids", [])
    ]
    invalid_ids = sorted(set(cited_ids) - VALID_IDS[condition])
    unprovided = sorted(
        term
        for term in UNPROVIDED_PROCEDURES
        if term.lower() in action_text.lower()
    )

    if condition == "llm_only":
        chain_evidence_policy = all(
            not item.get("evidence_ids") for item in chain if isinstance(item, dict)
        )
        claim_evidence_policy = all(
            not item.get("evidence_ids") for item in claims
        )
        action_evidence_policy = all(
            not item.get("evidence_ids") for item in actions
        )
    else:
        chain_evidence_policy = bool(chain) and all(
            item.get("evidence_ids")
            and all(evidence_id.startswith("G") for evidence_id in item["evidence_ids"])
            for item in chain
            if isinstance(item, dict)
        )
        claim_evidence_policy = bool(claims) and all(
            item.get("evidence_ids")
            and all(evidence_id.startswith("G") for evidence_id in item["evidence_ids"])
            for item in claims
        )
        allowed_action_prefixes = ("O",) if condition == "single_label_osf" else ("O", "T")
        action_evidence_policy = bool(actions) and all(
            item.get("evidence_ids")
            and all(
                evidence_id.startswith(allowed_action_prefixes)
                for evidence_id in item["evidence_ids"]
            )
            for item in actions
        )

    primary_osf = _contains(
        diagnosis.get("primary_failure_mode", ""),
        ("OSF", "overstrain", "오버스트레인", "과부하 변형"),
    )
    detects_twf = _contains(
        contributors,
        ("TWF", "tool wear", "공구 마모"),
    )
    explains_interaction = (
        _contains(
            diagnosis_text,
            ("tool wear", "공구 마모", "공구 수명", "TWF"),
        )
        and _contains(diagnosis_text, ("cutting resistance", "절삭 저항"))
        and _contains(
            diagnosis_text,
            ("overstrain", "오버스트레인", "OSF", "12,528"),
        )
    )

    checks = {
        "primary_osf": primary_osf,
        "detects_twf_contributor": detects_twf,
        "explains_twf_osf_interaction": explains_interaction,
        "feed_hold_safe_sequence": (
            _contains(action_text, ("feed hold", "이송 정지", "피드 홀드"))
            and _contains(action_text, ("safe position", "안전 위치"))
            and _contains(
                action_text,
                ("stop the spindle", "스핀들 정지", "스핀들을 정지"),
            )
        ),
        "damage_inspection": (
            _contains(action_text, ("breakage", "파손"))
            and _contains(
                action_text,
                ("runout", "런아웃", "clamp", "클램프", "feed axes", "이송축"),
            )
        ),
        "tool_replacement_and_reset": (
            _contains(
                action_text,
                ("new tool", "replace", "새 공구", "공구 교체"),
            )
            and _contains(
                action_text,
                ("offset", "counter", "오프셋", "수명 카운터"),
            )
        ),
        "cutting_parameter_review": (
            _contains(
                action_text,
                ("feed", "이송", "절삭 조건", "가공 조건"),
            )
            and _contains(action_text, ("15", "20%", "25", "감소", "줄"))
        ),
        "controlled_return": (
            _contains(
                action_text,
                ("dry run", "공절삭", "trial", "시험", "시운전"),
            )
            and _contains(
                action_text,
                ("30%", "supervisor", "감독자", "승인"),
            )
        ),
        "no_unprovided_procedures": not unprovided,
        "no_invalid_evidence_ids": not invalid_ids,
        "causal_chain_evidence_policy": chain_evidence_policy,
        "claim_evidence_policy": claim_evidence_policy,
        "action_evidence_policy": action_evidence_policy,
    }

    action_evidence = {
        evidence_id
        for item in actions
        for evidence_id in item.get("evidence_ids", [])
    }
    cross_sop_coverage = (
        any(evidence_id.startswith("O") for evidence_id in action_evidence)
        and any(evidence_id.startswith("T") for evidence_id in action_evidence)
    )

    return {
        "passed_checks": sum(bool(value) for value in checks.values()),
        "total_checks": len(checks),
        "pass_rate": round(
            sum(bool(value) for value in checks.values()) / len(checks),
            4,
        ),
        "checks": checks,
        "cross_sop_coverage": cross_sop_coverage,
        "invalid_evidence_ids": invalid_ids,
        "unprovided_procedures": unprovided,
        "action_count": len(actions),
        "uncertainty_count": len(response.get("uncertainties", [])),
    }


def run_codex(
    codex_bin: str,
    schema_path: Path,
    condition: str,
    repetition: int,
    model: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="forgeai-compound-eval-") as temp_dir:
        output_path = Path(temp_dir) / "response.json"
        completed = subprocess.run(
            [
                codex_bin,
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--skip-git-repo-check",
                "--model",
                model,
                "--config",
                f'model_reasoning_effort="{reasoning_effort}"',
                "--sandbox",
                "read-only",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "-C",
                temp_dir,
                "-",
            ],
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
    for condition in CONDITIONS:
        matching = [item for item in results if item.condition == condition]
        if not matching:
            continue
        summary[condition] = {
            "runs": len(matching),
            "mean_pass_rate": round(
                sum(item.score["pass_rate"] for item in matching) / len(matching),
                4,
            ),
            "primary_osf_accuracy": round(
                sum(item.score["checks"]["primary_osf"] for item in matching)
                / len(matching),
                4,
            ),
            "twf_contributor_detection": round(
                sum(
                    item.score["checks"]["detects_twf_contributor"]
                    for item in matching
                )
                / len(matching),
                4,
            ),
            "interaction_explanation_rate": round(
                sum(
                    item.score["checks"]["explains_twf_osf_interaction"]
                    for item in matching
                )
                / len(matching),
                4,
            ),
            "unprovided_procedure_runs": sum(
                bool(item.score["unprovided_procedures"]) for item in matching
            ),
            "complete_action_plan_runs": sum(
                all(
                    item.score["checks"][name]
                    for name in (
                        "feed_hold_safe_sequence",
                        "damage_inspection",
                        "tool_replacement_and_reset",
                        "cutting_parameter_review",
                        "controlled_return",
                    )
                )
                for item in matching
            ),
            "cross_sop_coverage_runs": sum(
                item.score["cross_sop_coverage"] for item in matching
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
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "compound_results",
    )
    args = parser.parse_args()

    schema_path = Path(__file__).resolve().parent / "compound_response_schema.json"
    run_dir = args.output_dir / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=False)

    results: list[RunResult] = []
    for repetition in range(1, args.repetitions + 1):
        for condition in CONDITIONS:
            response = run_codex(
                args.codex_bin,
                schema_path,
                condition,
                repetition,
                args.model,
                args.reasoning_effort,
            )
            score = score_response(condition, response)
            result = RunResult(condition, repetition, response, score)
            results.append(result)
            (run_dir / f"{condition}-{repetition}.json").write_text(
                json.dumps(
                    {
                        "condition": condition,
                        "repetition": repetition,
                        "response": response,
                        "score": score,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(
                f"{condition} run={repetition} "
                f"pass_rate={score['pass_rate']:.2%}",
                flush=True,
            )

    report = {
        "experiment": "compound-failure-grounding",
        "scenario_id": "twf-osf-compound-001",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repetitions_per_condition": args.repetitions,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "summary": summarize(results),
        "limitations": [
            "One synthetic compound-failure scenario cannot establish general RCA quality.",
            "Graph and SOP evidence are supplied in the prompt rather than queried from Neo4j.",
            "The deterministic scorer cannot replace blinded maintenance-expert review.",
        ],
    }
    (run_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"results_dir={run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
