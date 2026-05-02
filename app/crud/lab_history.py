import uuid
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.lab_history import PatientLabHistory
from app.models.patient import PatientProfile
from app.schemas.lab_history import LabHistoryCreate


async def record_lab_snapshot(
    db: AsyncSession, data: LabHistoryCreate
) -> PatientLabHistory:
    """Lab 수치 스냅샷을 INSERT하고, PatientProfile.lab_values를 최신값으로 갱신"""
    snapshot = PatientLabHistory(
        patient_id=data.patient_id,
        recorded_at=data.recorded_at,
        lab_values=data.lab_values.model_dump(exclude_none=True),
        source=data.source,
    )
    db.add(snapshot)

    result = await db.execute(
        select(PatientProfile).where(PatientProfile.id == data.patient_id)
    )
    patient = result.scalar_one_or_none()
    if patient:
        patient.lab_values = data.lab_values.model_dump(exclude_none=True)

    await db.commit()
    await db.refresh(snapshot)
    return snapshot


async def get_recent_lab_history(
    db: AsyncSession, patient_id: uuid.UUID, limit: int = 3
) -> list[PatientLabHistory]:
    """최근 N회 Lab 기록 (최신순)"""
    result = await db.execute(
        select(PatientLabHistory)
        .where(PatientLabHistory.patient_id == patient_id)
        .order_by(PatientLabHistory.recorded_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def record_lab_snapshot_raw(
    db: AsyncSession,
    patient_id: uuid.UUID,
    recorded_at: datetime,
    lab_values: dict,
    source: str,
) -> PatientLabHistory:
    """OCR 파싱 결과(raw dict)를 PatientLabHistory에 직접 저장."""
    snapshot = PatientLabHistory(
        patient_id=patient_id,
        recorded_at=recorded_at,
        lab_values=lab_values,
        source=source,
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)
    return snapshot
