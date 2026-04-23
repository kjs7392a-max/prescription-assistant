import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.patient import PatientProfile
from app.schemas.patient import PatientProfileCreate, PatientProfileUpdate


async def create_patient(db: AsyncSession, data: PatientProfileCreate) -> PatientProfile:
    patient = PatientProfile(
        patient_code=data.patient_code,
        age=data.age,
        gender=data.gender,
        weight_kg=data.weight_kg,
        height_cm=data.height_cm,
        diseases=data.diseases.model_dump(),
        lab_values=data.lab_values.model_dump(),
        allergies=data.allergies,
        current_medications=data.current_medications,
        clinical_notes=data.clinical_notes,
    )
    db.add(patient)
    await db.commit()
    await db.refresh(patient)
    return patient


async def get_patient(db: AsyncSession, patient_id: uuid.UUID) -> PatientProfile | None:
    result = await db.execute(select(PatientProfile).where(PatientProfile.id == patient_id))
    return result.scalar_one_or_none()


async def get_patient_by_code(db: AsyncSession, patient_code: str) -> PatientProfile | None:
    result = await db.execute(
        select(PatientProfile).where(PatientProfile.patient_code == patient_code)
    )
    return result.scalar_one_or_none()


async def list_patients(db: AsyncSession, skip: int = 0, limit: int = 50) -> list[PatientProfile]:
    result = await db.execute(select(PatientProfile).offset(skip).limit(limit))
    return list(result.scalars().all())


async def update_patient(
    db: AsyncSession, patient: PatientProfile, data: PatientProfileUpdate
) -> PatientProfile:
    for field, value in data.model_dump(exclude_none=True).items():
        if field == "diseases":
            setattr(patient, field, value.model_dump() if hasattr(value, "model_dump") else value)
        elif field == "lab_values":
            setattr(patient, field, value.model_dump() if hasattr(value, "model_dump") else value)
        else:
            setattr(patient, field, value)
    await db.commit()
    await db.refresh(patient)
    return patient
