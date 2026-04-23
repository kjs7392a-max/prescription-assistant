import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.feedback import PrescriptionFeedback
from app.schemas.feedback import FeedbackCreate


async def create_feedback(
    db: AsyncSession, data: FeedbackCreate
) -> PrescriptionFeedback:
    feedback = PrescriptionFeedback(**data.model_dump())
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)
    return feedback


async def get_patient_feedbacks(
    db: AsyncSession, patient_id: uuid.UUID
) -> list[PrescriptionFeedback]:
    """환자의 모든 부작용·수정 이력 (최신순) — Inference Engine 우선순위 1"""
    result = await db.execute(
        select(PrescriptionFeedback)
        .where(PrescriptionFeedback.patient_id == patient_id)
        .order_by(PrescriptionFeedback.created_at.desc())
    )
    return list(result.scalars().all())


async def get_adverse_events(
    db: AsyncSession, patient_id: uuid.UUID
) -> list[PrescriptionFeedback]:
    """부작용(adverse_event)만 필터링 — 금기 성분 식별용"""
    result = await db.execute(
        select(PrescriptionFeedback)
        .where(
            PrescriptionFeedback.patient_id == patient_id,
            PrescriptionFeedback.feedback_type == "adverse_event",
        )
    )
    return list(result.scalars().all())
