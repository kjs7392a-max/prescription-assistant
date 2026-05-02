import uuid
import os
from datetime import datetime
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.lab_ocr import parse_image, parse_text
from app.crud import lab_submission as sub_crud
from app.crud import lab_history as lab_hist_crud
from app.crud import patient as patient_crud
from app.schemas.lab_submission import LabSubmissionResponse, LabSubmissionConfirm, LabSubmissionCreate

router = APIRouter(prefix="/lab-upload", tags=["lab-upload"])

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "lab_photos")


class TextParseRequest(BaseModel):
    raw_text: str


@router.post("/photo", response_model=LabSubmissionResponse, status_code=201)
async def upload_photo(
    photo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    image_bytes = await photo.read()
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="사진 크기가 10MB를 초과합니다.")

    filename = f"{uuid.uuid4()}.jpg"
    file_path = os.path.join(UPLOAD_DIR, filename)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with open(file_path, "wb") as f:
        f.write(image_bytes)

    ocr_result = await parse_image(image_bytes)
    relative_path = f"uploads/lab_photos/{filename}"

    data = LabSubmissionCreate(
        photo_path=relative_path,
        parsed_values=ocr_result if ocr_result["parsed"] else None,
        raw_text=ocr_result["raw_text"],
        is_parsed=ocr_result["parsed"],
        source="photo",
    )
    return await sub_crud.create_submission(db=db, data=data)


@router.post("/text")
async def parse_emr_text(body: TextParseRequest):
    return await parse_text(body.raw_text)


@router.get("/pending", response_model=list[LabSubmissionResponse])
async def get_pending(db: AsyncSession = Depends(get_db)):
    return await sub_crud.list_pending(db)


@router.patch("/{submission_id}/confirm", response_model=LabSubmissionResponse)
async def confirm_submission(
    submission_id: uuid.UUID,
    body: LabSubmissionConfirm,
    db: AsyncSession = Depends(get_db),
):
    sub = await sub_crud.get_submission(db, submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="제출 건을 찾을 수 없습니다.")
    patient = await patient_crud.get_patient_by_code(db, body.patient_code)
    if not patient:
        raise HTTPException(status_code=404, detail=f"차트번호 {body.patient_code} 환자를 찾을 수 없습니다.")
    await lab_hist_crud.record_lab_snapshot_raw(
        db=db,
        patient_id=patient.id,
        recorded_at=body.recorded_at,
        lab_values=body.lab_values,
        source="qr_photo",
    )
    return await sub_crud.mark_saved(db, sub, patient.id)
