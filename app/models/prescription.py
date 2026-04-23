import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, Float, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class PrescriptionLog(Base):
    """처방 가이드 이력 — 성분명 기반 추천 결과 저장"""
    __tablename__ = "prescription_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # 연결 키
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patient_profiles.id"), nullable=False, index=True
    )
    # 동일 세션의 복수 약물을 묶는 그룹 키
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    drug_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drug_knowledge_base.id"), nullable=False
    )

    # 추천 내용 (성분명 + 함량 — 상품명 없음)
    recommended_generic_name_ko: Mapped[str] = mapped_column(String(200), nullable=False)
    recommended_generic_name_en: Mapped[str] = mapped_column(String(200), nullable=False)
    recommended_strength_mg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recommended_dose_description: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_frequency: Mapped[str] = mapped_column(String(100), nullable=False)
    recommended_duration_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 근거 및 임상 설명
    clinical_rationale: Mapped[str] = mapped_column(Text, nullable=False)
    guideline_reference: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    warnings: Mapped[list] = mapped_column(ARRAY(Text), nullable=False, default=list)
    physician_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # ORM 관계
    patient: Mapped["PatientProfile"] = relationship("PatientProfile", lazy="selectin")
    drug: Mapped["DrugKnowledgeBase"] = relationship("DrugKnowledgeBase", lazy="selectin")
