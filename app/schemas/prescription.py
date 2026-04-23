import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class PrescriptionLogCreate(BaseModel):
    patient_id: uuid.UUID
    session_id: uuid.UUID
    drug_id: uuid.UUID
    recommended_generic_name_ko: str
    recommended_generic_name_en: str
    recommended_strength_mg: Optional[float] = None
    recommended_dose_description: str
    recommended_frequency: str
    recommended_duration_days: Optional[int] = None
    clinical_rationale: str
    guideline_reference: Optional[str] = None
    warnings: list[str] = []
    physician_notes: Optional[str] = None


class PrescriptionLogResponse(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    session_id: uuid.UUID
    drug_id: uuid.UUID
    recommended_generic_name_ko: str
    recommended_generic_name_en: str
    recommended_strength_mg: Optional[float]
    recommended_dose_description: str
    recommended_frequency: str
    recommended_duration_days: Optional[int]
    clinical_rationale: str
    guideline_reference: Optional[str]
    warnings: list[str]
    physician_notes: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}
