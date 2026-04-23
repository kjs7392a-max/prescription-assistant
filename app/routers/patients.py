import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.patient import PatientProfileCreate, PatientProfileUpdate, PatientProfileResponse
from app.crud import patient as patient_crud

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post("/", response_model=PatientProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_patient(data: PatientProfileCreate, db: AsyncSession = Depends(get_db)):
    existing = await patient_crud.get_patient_by_code(db, data.patient_code)
    if existing:
        raise HTTPException(status_code=409, detail="Patient code already exists")
    return await patient_crud.create_patient(db, data)


@router.get("/{patient_id}", response_model=PatientProfileResponse)
async def get_patient(patient_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    patient = await patient_crud.get_patient(db, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@router.get("/", response_model=list[PatientProfileResponse])
async def list_patients(skip: int = 0, limit: int = 50, db: AsyncSession = Depends(get_db)):
    return await patient_crud.list_patients(db, skip, limit)


@router.patch("/{patient_id}", response_model=PatientProfileResponse)
async def update_patient(
    patient_id: uuid.UUID, data: PatientProfileUpdate, db: AsyncSession = Depends(get_db)
):
    patient = await patient_crud.get_patient(db, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return await patient_crud.update_patient(db, patient, data)
