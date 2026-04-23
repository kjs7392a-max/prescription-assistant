import uuid
from datetime import date
from typing import Optional
from pydantic import BaseModel
from app.models.patient import LabValues, DiseaseFlags


class InferenceRequest(BaseModel):
    patient_id: uuid.UUID
    visit_date: date
    current_lab_values: Optional[LabValues] = None
    disease_updates: Optional[DiseaseFlags] = None
    physician_note: str


class RecommendedGeneric(BaseModel):
    generic_name_ko: str
    generic_name_en: str
    strength_mg: Optional[float] = None
    frequency: str
    rationale: str
    guideline_reference: Optional[str] = None
    risk_level: str
    warnings: list[str] = []


class InferenceResponse(BaseModel):
    recommended_generics: list[RecommendedGeneric]
    contraindicated_generics: list[str]
    lab_delta_summary: str
    overall_risk: str
    physician_action_required: bool
