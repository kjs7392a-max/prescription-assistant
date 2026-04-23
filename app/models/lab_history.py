import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class PatientLabHistory(Base):
    """환자 Lab 수치 시계열 스냅샷 — 진료 시점마다 INSERT, 덮어쓰기 없음"""
    __tablename__ = "patient_lab_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patient_profiles.id"), nullable=False, index=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    lab_values: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")

    patient: Mapped["PatientProfile"] = relationship("PatientProfile", lazy="selectin")
