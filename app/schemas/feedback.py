import uuid
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel


class FeedbackCreate(BaseModel):
    prescription_log_id: uuid.UUID
    patient_id: uuid.UUID
    feedback_type: Literal["adverse_event", "physician_override", "dose_adjusted"]
    severity: Optional[Literal["mild", "moderate", "severe"]] = None
    description: str
    affected_generic_ko: str
    affected_generic_en: str
    recorded_by: Optional[str] = None


class FeedbackResponse(BaseModel):
    id: uuid.UUID
    prescription_log_id: uuid.UUID
    patient_id: uuid.UUID
    feedback_type: str
    severity: Optional[str]
    description: str
    affected_generic_ko: str
    affected_generic_en: str
    recorded_by: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}
