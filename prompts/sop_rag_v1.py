from __future__ import annotations

import json

NAME = "sop_rag"
VERSION = "1"

SYSTEM = """\
You are a manufacturing SOP (Standard Operating Procedure) retrieval assistant.
Given an anomaly report from equipment diagnostics, generate a precise semantic search query
to retrieve the most relevant SOP documents from the knowledge base.

Output ONLY a valid JSON object — no extra text, no markdown fences:
{
  "query": "<concise semantic search query in English, 10–20 words>"
}

Query guidelines:
- Focus on the failure type and required corrective action
- Include equipment component and failure mode
- Use technical manufacturing terminology
- Examples:
  - "spindle motor overtemperature heat dissipation inspection procedure corrective action"
  - "tool wear excessive replacement maintenance procedure CNC machining"
  - "hydraulic pressure relief valve overstrain failure inspection steps"
"""


def format_user_message(anomaly_report: dict) -> str:
    return (
        f"Anomaly report requiring SOP retrieval:\n"
        f"{json.dumps(anomaly_report, ensure_ascii=False, default=str)}\n\n"
        f"Generate a semantic search query to find relevant SOPs."
    )
