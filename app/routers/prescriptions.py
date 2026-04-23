import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.prescription import PrescriptionLogCreate, PrescriptionLogResponse
from app.crud import prescription as prescription_crud

router = APIRouter(prefix="/prescriptions", tags=["prescriptions"])


@router.post("/", response_model=PrescriptionLogResponse, status_code=status.HTTP_201_CREATED)
async def create_prescription_log(
    data: PrescriptionLogCreate, db: AsyncSession = Depends(get_db)
):
    return await prescription_crud.create_prescription_log(db, data)


@router.get("/patient/{patient_id}", response_model=list[PrescriptionLogResponse])
async def get_patient_prescriptions(
    patient_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    return await prescription_crud.get_logs_by_patient(db, patient_id)


@router.get("/session/{session_id}", response_model=list[PrescriptionLogResponse])
async def get_session_prescriptions(
    session_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    return await prescription_crud.get_logs_by_session(db, session_id)
