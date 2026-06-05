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
"""


def format_user_message(
    anomaly_report: dict,
    sop_chunks: list[dict],
    previous_feedback: str | None = None,
    retry_attempt: int = 0,
) -> str:
    chunks_text = "\n".join(
        f"[chunk_id: {c['chunk_id']}] {c['text'][:400]}"
        for c in sop_chunks
    )
    base = (
        f"ANOMALY REPORT:\n{json.dumps(anomaly_report, ensure_ascii=False, default=str)}\n\n"
        f"RELEVANT SOP CHUNKS:\n{chunks_text}\n\n"
    )
    if previous_feedback and retry_attempt > 0:
        base += (
            f"PREVIOUS ATTEMPT FEEDBACK (attempt {retry_attempt}):\n{previous_feedback}\n\n"
            f"The previous action plan was REJECTED. Revise it addressing the feedback above.\n\n"
        )
    return base + "Generate a prioritized maintenance action plan based on the above."
