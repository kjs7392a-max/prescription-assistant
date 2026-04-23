import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from app.models.patient import LabValues


class LabHistoryCreate(BaseModel):
    patient_id: uuid.UUID
    recorded_at: datetime
    lab_values: LabValues
    source: str = "manual"


class LabHistoryResponse(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    recorded_at: datetime
    lab_values: dict
    source: str

    model_config = {"from_attributes": True}
