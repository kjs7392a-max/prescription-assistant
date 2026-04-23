import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class PrescriptionFeedback(Base):
    """처방 부작용·의사 수정 이력 — Inference Engine 최우선 컨텍스트"""
    __tablename__ = "prescription_feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    prescription_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prescription_logs.id"), nullable=False, index=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patient_profiles.id"), nullable=False, index=True
    )
    # "adverse_event" | "physician_override" | "dose_adjusted"
    feedback_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # "mild" | "moderate" | "severe" | null
    severity: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    affected_generic_ko: Mapped[str] = mapped_column(String(200), nullable=False)
    affected_generic_en: Mapped[str] = mapped_column(String(200), nullable=False)
    recorded_by: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    prescription_log: Mapped["PrescriptionLog"] = relationship("PrescriptionLog", lazy="selectin")
    patient: Mapped["PatientProfile"] = relationship("PatientProfile", lazy="selectin")
