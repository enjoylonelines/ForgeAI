from __future__ import annotations

import json

NAME = "action_plan"
VERSION = "1"

SYSTEM = """\
You are a manufacturing maintenance planning system.
Given an anomaly report and relevant SOP document chunks, generate a prioritized action plan.

Output ONLY valid JSON matching this exact schema — no extra text, no markdown fences:
{
  "equipment_id": "<string>",
  "generated_at": "<ISO8601 string>",
  "steps": [
    {
      "step_number": <integer starting at 1>,
      "action": "<specific actionable instruction>",
      "responsible_role": "<role: maintenance_technician | shift_supervisor | safety_officer | engineer>",
      "priority": "P1" | "P2" | "P3",
      "estimated_duration_minutes": <integer or null>,
      "sop_reference": "<exact chunk_id from provided SOP context, e.g. SOP-MNT-001.md::chunk::3>"
    }
  ],
  "escalation_required": <true|false>,
  "escalation_reason": "<string or null>"
}

Rules:
- Each step MUST cite the exact chunk_id from the SOP context in sop_reference
- Do NOT invent SOP references — only use chunk_ids provided in the context
- If no relevant SOP chunk exists for a step, set sop_reference to null
- Priority: P1=immediate safety/production stop risk, P2=within 1 hour, P3=within shift
- escalation_required=true if any anomaly severity is CRITICAL or if power/safety systems are involved
- Generate 3–7 steps ordered by urgency
- For each step's action text, use key phrases and terminology VERBATIM from the cited SOP chunk — do not paraphrase when exact wording is available
"""


_FAILURE_TYPE_ADDENDUM: dict[str, str] = {
    "TWF": (
        "FAILURE TYPE CONTEXT — Tool Wear Failure (TWF):\n"
        "The root cause is excessive tool wear (>200 min). Prioritize immediate tool replacement.\n"
        "Steps must include: (1) machine stop, (2) tool inspection and replacement, "
        "(3) verification of cutting parameters, (4) post-replacement run test.\n"
    ),
    "HDF": (
        "FAILURE TYPE CONTEXT — Heat Dissipation Failure (HDF):\n"
        "The root cause is insufficient heat dissipation: temperature differential <8.6 K combined "
        "with low spindle speed. Prioritize cooling system inspection.\n"
        "Steps must include: (1) reduce spindle load, (2) inspect coolant flow and heat exchangers, "
        "(3) verify air circulation around spindle, (4) thermal sensor calibration check.\n"
    ),
    "PWF": (
        "FAILURE TYPE CONTEXT — Power Failure (PWF):\n"
        "The root cause is spindle power operating outside 3500–9000 W safe range. "
        "Prioritize electrical and drive system inspection.\n"
        "Steps must include: (1) check drive inverter and motor connections, "
        "(2) verify power supply stability, (3) review cutting parameters for power balance, "
        "(4) spindle motor load test.\n"
    ),
    "OSF": (
        "FAILURE TYPE CONTEXT — Overstrain Failure (OSF):\n"
        "The root cause is mechanical overstrain: tool wear × torque product exceeds safe threshold. "
        "Prioritize load reduction and structural inspection.\n"
        "Steps must include: (1) reduce feed rate and depth of cut, (2) inspect chuck and tool holder "
        "for deformation, (3) check spindle bearing play, (4) replace worn tooling.\n"
    ),
}


def get_system_prompt(failure_type: str | None = None) -> str:
    """Return the system prompt, unchanged — failure type context goes in the user message."""
    return SYSTEM


def format_user_message(
    anomaly_report: dict,
    sop_chunks: list[dict],
    previous_feedback: str | None = None,
    retry_attempt: int = 0,
    failure_type: str | None = None,
) -> str:
    chunks_text = "\n".join(
        f"[chunk_id: {c['chunk_id']}] {c['text'][:600]}"
        for c in sop_chunks
    )
    base = ""
    if failure_type and failure_type in _FAILURE_TYPE_ADDENDUM:
        base += _FAILURE_TYPE_ADDENDUM[failure_type] + "\n"
    base += (
        f"ANOMALY REPORT:\n{json.dumps(anomaly_report, ensure_ascii=False, default=str)}\n\n"
        f"RELEVANT SOP CHUNKS:\n{chunks_text}\n\n"
    )
    if previous_feedback and retry_attempt > 0:
        base += (
            f"PREVIOUS ATTEMPT FEEDBACK (attempt {retry_attempt}):\n{previous_feedback}\n\n"
            f"The previous action plan was REJECTED. Revise it addressing the feedback above.\n\n"
        )
    return base + "Generate a prioritized maintenance action plan based on the above."
