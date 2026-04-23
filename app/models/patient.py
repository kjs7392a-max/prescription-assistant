import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, Float, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from pydantic import BaseModel
from app.database import Base


class DiseaseFlags(BaseModel):
    """15대 주요 질환 플래그 — Pydantic 검증 후 JSONB에 저장"""
    hypertension: bool = False          # 고혈압
    diabetes_type1: bool = False        # 1형 당뇨
    diabetes_type2: bool = False        # 2형 당뇨
    hyperlipidemia: bool = False        # 고지혈증
    coronary_artery_disease: bool = False  # 관상동맥질환
    heart_failure: bool = False         # 심부전
    atrial_fibrillation: bool = False   # 심방세동
    stroke: bool = False                # 뇌졸중/TIA
    ckd: bool = False                   # 만성신장질환
    ckd_stage: Optional[int] = None     # CKD 병기 (1-5)
    liver_disease: bool = False         # 간질환
    copd: bool = False                  # 만성폐쇄성폐질환
    asthma: bool = False                # 천식
    thyroid_disease: bool = False       # 갑상선질환
    osteoporosis: bool = False          # 골다공증
    gout: bool = False                  # 통풍
    depression_anxiety: bool = False    # 우울/불안장애


class LabValues(BaseModel):
    """주요 검사 수치 — Pydantic 검증 후 JSONB에 저장"""
    # 신장 기능
    creatinine: Optional[float] = None      # mg/dL
    egfr: Optional[float] = None            # mL/min/1.73m²
    # 혈당
    hba1c: Optional[float] = None           # %
    fasting_glucose: Optional[float] = None # mg/dL
    # 지질
    ldl: Optional[float] = None             # mg/dL
    hdl: Optional[float] = None             # mg/dL
    total_cholesterol: Optional[float] = None
    triglycerides: Optional[float] = None   # mg/dL
    # 간 기능
    ast: Optional[float] = None             # U/L
    alt: Optional[float] = None             # U/L
    bilirubin_total: Optional[float] = None # mg/dL
    # 갑상선
    tsh: Optional[float] = None             # mIU/L
    free_t4: Optional[float] = None         # ng/dL
    # 통풍
    uric_acid: Optional[float] = None       # mg/dL
    # 혈액
    hemoglobin: Optional[float] = None      # g/dL
    wbc: Optional[float] = None             # ×10³/μL
    platelet: Optional[float] = None        # ×10³/μL
    # 항응고
    inr: Optional[float] = None
    # 심부전
    nt_probnp: Optional[float] = None       # pg/mL
    bnp: Optional[float] = None             # pg/mL
    # 전해질
    sodium: Optional[float] = None          # mEq/L
    potassium: Optional[float] = None       # mEq/L


class PatientProfile(Base):
    __tablename__ = "patient_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    gender: Mapped[str] = mapped_column(String(1), nullable=False)  # M / F
    weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    height_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 15대 질환 플래그 (JSONB)
    diseases: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # 검사 수치 (JSONB)
    lab_values: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    allergies: Mapped[list] = mapped_column(ARRAY(Text), nullable=False, default=list)
    current_medications: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    clinical_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
