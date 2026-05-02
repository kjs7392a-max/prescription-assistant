import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.lab_submission import LabSubmission


async def create_submission(
    db: AsyncSession,
    photo_path: str,
    parsed_values: dict | None,
    raw_text: str | None,
    is_parsed: bool,
    source: str = "photo",
) -> LabSubmission:
    sub = LabSubmission(
        photo_path=photo_path,
        parsed_values=parsed_values,
        raw_text=raw_text,
        is_parsed=is_parsed,
        source=source,
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
