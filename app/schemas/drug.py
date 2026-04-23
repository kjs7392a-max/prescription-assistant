import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class DrugKnowledgeBaseCreate(BaseModel):
    generic_name_ko: str
    generic_name_en: str
    drug_class: str
    indications: list[str]
    contraindications: dict                # {"absolute": [...], "relative": [...]}
    standard_dosage: dict                  # {"initial": {...}, "maintenance": {...}, "max_daily_mg": N}
    dose_forms: list[str]
    strengths_available_mg: list[float]
    guideline_source: str
    guideline_year: int
    guideline_url: Optional[str] = None
    special_populations: dict = {}
    drug_interactions: list[str] = []
    monitoring_parameters: list[str] = []
    clinical_notes: Optional[str] = None


class DrugKnowledgeBaseUpdate(BaseModel):
    drug_class: Optional[str] = None
    indications: Optional[list[str]] = None
    contraindications: Optional[dict] = None
    standard_dosage: Optional[dict] = None
    dose_forms: Optional[list[str]] = None
    strengths_available_mg: Optional[list[float]] = None
    guideline_source: Optional[str] = None
    guideline_year: Optional[int] = None
    guideline_url: Optional[str] = None
    special_populations: Optional[dict] = None
    drug_interactions: Optional[list[str]] = None
    monitoring_parameters: Optional[list[str]] = None
    clinical_notes: Optional[str] = None


class DrugKnowledgeBaseResponse(BaseModel):
    id: uuid.UUID
    generic_name_ko: str
    generic_name_en: str
    drug_class: str
    indications: list[str]
    contraindications: dict
    standard_dosage: dict
    dose_forms: list[str]
    strengths_available_mg: list
    guideline_source: str
    guideline_year: int
    guideline_url: Optional[str]
    special_populations: dict
    drug_interactions: list[str]
    monitoring_parameters: list[str]
    clinical_notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
