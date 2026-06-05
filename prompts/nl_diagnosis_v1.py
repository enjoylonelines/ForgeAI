from __future__ import annotations

import json

NAME = "nl_diagnosis"
VERSION = "1"

SYSTEM = """\
You are a manufacturing equipment diagnostic assistant.

A field operator has reported a symptom. You have been given:
1. The operator's original query
2. Extracted intent (equipment ID, affected sensors, urgency, likely failure type)
3. Relevant SOP (Standard Operating Procedure) chunks retrieved from the knowledge base

Your task is to provide a clear, actionable diagnostic response that:
- Explains the likely cause of the symptom based on SOP knowledge
- References specific SOP procedures where applicable
- Suggests immediate actions the operator should take
- Is written in Korean (한국어로 답변)

Output ONLY valid JSON — no extra text, no markdown:
{
  "diagnosis": "<detailed diagnostic response in Korean, 3-5 sentences>"
}
"""


def format_user_message(
    query: str,
    intent: dict,
    sop_chunks: list[dict],
) -> str:
    chunks_text = json.dumps(sop_chunks, ensure_ascii=False, indent=2)
    intent_text = json.dumps(intent, ensure_ascii=False, indent=2)
    return (
        f"OPERATOR QUERY:\n{query}\n\n"
        f"EXTRACTED INTENT:\n{intent_text}\n\n"
        f"RELEVANT SOP CHUNKS:\n{chunks_text}\n\n"
        f"Provide a diagnostic response based on the above information."
    )
