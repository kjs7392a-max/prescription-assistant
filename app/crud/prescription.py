import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.prescription import PrescriptionLog
from app.schemas.prescription import PrescriptionLogCreate


async def create_prescription_log(
    db: AsyncSession, data: PrescriptionLogCreate
) -> PrescriptionLog:
    log = PrescriptionLog(**data.model_dump())
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


async def get_logs_by_patient(
    db: AsyncSession, patient_id: uuid.UUID
) -> list[PrescriptionLog]:
    result = await db.execute(
        select(PrescriptionLog)
        .where(PrescriptionLog.patient_id == patient_id)
        .order_by(PrescriptionLog.created_at.desc())
    )
    return list(result.scalars().all())


async def get_logs_by_session(
    db: AsyncSession, session_id: uuid.UUID
) -> list[PrescriptionLog]:
    result = await db.execute(
        select(PrescriptionLog).where(PrescriptionLog.session_id == session_id)
    )
    return list(result.scalars().all())
