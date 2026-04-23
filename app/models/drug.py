import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class DrugKnowledgeBase(Base):
    """성분명(Generic) 기반 약물 지식 DB — 상품명 저장 금지"""
    __tablename__ = "drug_knowledge_base"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # 성분명 (한글/영문 병기)
    generic_name_ko: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    generic_name_en: Mapped[str] = mapped_column(String(200), nullable=False, index=True)

    # 약물 분류
    drug_class: Mapped[str] = mapped_column(String(200), nullable=False)

    # 적응증
    indications: Mapped[list] = mapped_column(ARRAY(Text), nullable=False, default=list)

    # 금기 (절대/상대 구분)
    # {"absolute": [...], "relative": [...]}
    contraindications: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # 표준 용량 (근거 기반)
    # {"initial": {dose_mg, frequency, route}, "maintenance": {...}, "max_daily_mg": N}
    standard_dosage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # 제형 (tablet, capsule, injection, XR-tablet 등)
    dose_forms: Mapped[list] = mapped_column(ARRAY(Text), nullable=False, default=list)

    # 가용 함량 (mg 단위 숫자 배열)
    strengths_available_mg: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # 근거 가이드라인
    guideline_source: Mapped[str] = mapped_column(Text, nullable=False)
    guideline_year: Mapped[int] = mapped_column(Integer, nullable=False)
    guideline_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 특수 집단 용량 조정
    # {"renal": {...}, "hepatic": ..., "elderly": ..., "pediatric": ..., "pregnancy": ...}
    special_populations: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # 약물 상호작용 (성분명 목록)
    drug_interactions: Mapped[list] = mapped_column(ARRAY(Text), nullable=False, default=list)

    # 모니터링 항목
    monitoring_parameters: Mapped[list] = mapped_column(ARRAY(Text), nullable=False, default=list)

    # 추가 임상 노트
    clinical_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
