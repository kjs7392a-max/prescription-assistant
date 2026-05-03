import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.lab_submission import LabSubmission
from app.schemas.lab_submission import LabSubmissionCreate


async def create_submission(db: AsyncSession, data: LabSubmissionCreate) -> LabSubmission:
    sub = LabSubmission(
        photo_path=data.photo_path,
        parsed_values=data.parsed_values,
        raw_text=data.raw_text,
        is_parsed=data.is_parsed,
        source=data.source,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


async def list_pending(db: AsyncSession) -> list[LabSubmission]:
    result = await db.execute(
        select(LabSubmission)
        .where(LabSubmission.status == "pending")
        .order_by(LabSubmission.created_at.desc())
    )
    return list(result.scalars().all())


async def get_submission(db: AsyncSession, submission_id: uuid.UUID) -> LabSubmission | None:
    result = await db.execute(
        select(LabSubmission).where(LabSubmission.id == submission_id)
    )
    return result.scalar_one_or_none()


async def mark_saved(
    db: AsyncSession, sub: LabSubmission, patient_id: uuid.UUID
) -> LabSubmission:
    sub.status = "saved"
    sub.patient_id = patient_id
    await db.commit()
    await db.refresh(sub)
    return sub
