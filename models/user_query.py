from __future__ import annotations

from pydantic import BaseModel

from models.sop_context import SOPChunk


class UserQueryRequest(BaseModel):
    query: str
    equipment_id: str | None = None


class ExtractedIntent(BaseModel):
    equipment_id: str | None = None
    symptom_description: str
    sensor_types: list[str]
    urgency: str  # "low" | "medium" | "high"
    failure_type_hints: list[str]  # e.g. ["TWF", "HDF"]


class NLDiagnosisResult(BaseModel):
    query: str
    intent: ExtractedIntent
    diagnosis: str
    related_sop_chunks: list[SOPChunk]
    correlation_id: str
