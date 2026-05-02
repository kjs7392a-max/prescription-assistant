import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class LabSubmissionResponse(BaseModel):
    id: uuid.UUID
    photo_path: Optional[str]
    parsed_values: Optional[dict]
    is_parsed: bool
    patient_id: Optional[uuid.UUID]
    source: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class LabSubmissionConfirm(BaseModel):
    patient_code: str
    lab_values: dict
    recorded_at: datetime
