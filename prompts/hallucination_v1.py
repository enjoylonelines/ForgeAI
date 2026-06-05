from __future__ import annotations

import json

NAME = "hallucination"
VERSION = "1"

SYSTEM = """\
You are a manufacturing safety compliance auditor.
An action plan has been found to contain steps NOT grounded in the provided SOP documents.
Your task is to explain which steps are problematic and why, in a concise audit note.

Output ONLY valid JSON — no extra text, no markdown fences:
{
  "explanation": "<2–4 sentence audit explanation of ungrounded steps and recommended review>"
}
"""


def format_user_message(
    action_plan: dict,
    ungrounded_steps: list[int],
    overall_score: float,
) -> str:
    return (
        f"Action plan with ungrounded steps requiring audit:\n"
        f"{json.dumps(action_plan, ensure_ascii=False, default=str)}\n\n"
        f"Ungrounded step numbers: {ungrounded_steps}\n"
        f"Overall grounding score: {overall_score:.2f}\n\n"
        f"Provide an audit explanation for the compliance record."
    )
