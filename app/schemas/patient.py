import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from app.models.patient import DiseaseFlags, LabValues


class PatientProfileCreate(BaseModel):
    patient_code: str
    age: int
    gender: str
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None
    diseases: DiseaseFlags = DiseaseFlags()
    lab_values: LabValues = LabValues()
    allergies: list[str] = []
    current_medications: Optional[dict] = None
    clinical_notes: Optional[str] = None


class PatientProfileUpdate(BaseModel):
    age: Optional[int] = None
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None
    diseases: Optional[DiseaseFlags] = None
    lab_values: Optional[LabValues] = None
    allergies: Optional[list[str]] = None
    current_medications: Optional[dict] = None
    clinical_notes: Optional[str] = None


class PatientProfileResponse(BaseModel):
    id: uuid.UUID
    patient_code: str
    age: int
    gender: str
    weight_kg: Optional[float]
    height_cm: Optional[float]
    diseases: dict
    lab_values: dict
    allergies: list[str]
    current_medications: Optional[dict]
    clinical_notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
