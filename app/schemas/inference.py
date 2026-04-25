import uuid
from datetime import date
from typing import Optional, Literal
from pydantic import BaseModel
from app.models.patient import LabValues, DiseaseFlags


class InferenceRequest(BaseModel):
    patient_id: uuid.UUID
    visit_date: date
    current_lab_values: Optional[LabValues] = None
    disease_updates: Optional[DiseaseFlags] = None
    physician_note: str


class RecommendedGeneric(BaseModel):
    generic_name_ko: str
    generic_name_en: str
    strength_mg: Optional[float] = None
    frequency: str
    rationale: str
    guideline_reference: Optional[str] = None
    risk_level: str
    warnings: list[str] = []
    dose_adjustment: Optional[str] = None
    drug_category: Optional[str] = None
    intake_instruction: Optional[str] = None


class SafetyWarning(BaseModel):
    level: Literal["contraindication", "caution", "dose"]
    text: str


class PrescriptionSummary(BaseModel):
    summary: str


class CompactDetails(BaseModel):
    guidelines: str = ""
    rct: str = ""
    notes: str = ""


class GDMTStep(BaseModel):
    step: int            # 1~5 (5 = 정신건강 관리)
    drug: str
    note: str = ""


class PsychiatricRec(BaseModel):
    detected: bool = False
    drug: str = ""
    consult: str = ""


class RxItem(BaseModel):
    generic_name_ko: str
    strength: str = ""              # "10mg" 등
    frequency: str = ""             # "QD/BID/TID" 또는 "1일 1회 아침" 등
    form_description: str = ""      # "흰색 원형 정제", "노란색 서방정" 등 복약 안내문 느낌
    category: str = ""              # "주치료"|"방어제"|"정신과"
    note: str = ""                  # 1줄 사유


class RecommendationSet(BaseModel):
    primary: list[RxItem] = []      # 1차 추천 세트 (주치료 + 방어제 + 정신과)
    secondary: list[RxItem] = []    # 2차 대체 세트


class InferenceResponse(BaseModel):
    # ── 표준 출력 템플릿 ──
    core: str = ""
    recommendation_set: RecommendationSet = RecommendationSet()  # [1·2차 처방 추천]
    gdmt_steps: list[GDMTStep] = []                                # Step 1~5 (5=정신건강)
    psychiatric: PsychiatricRec = PsychiatricRec()
    warnings: list[str] = []
    guidelines: list[str] = []
    details: CompactDetails = CompactDetails()

    # ── 하위 호환 (테스트·기존 호출자) ──
    safetyWarnings: list[SafetyWarning] = []
    prescription: PrescriptionSummary = PrescriptionSummary(summary="")
    reasons: list[str] = []
    prescription_set: list[RecommendedGeneric] = []
    recommended_generics: list[RecommendedGeneric] = []
    contraindicated_generics: list[str] = []
    lab_delta_summary: str = ""
    overall_risk: str = "moderate"
    physician_action_required: bool = True
    evidence_commentary: str = ""
    key_rct_references: list[str] = []
    deep_insight: str = ""
