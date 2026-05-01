from typing import Literal, Optional
from pydantic import BaseModel


class NormalizedDrug(BaseModel):
    raw_name: str
    normalized_name: str
    ingredient_code: Optional[str] = None       # ATC code (e.g. "A10BA02")
    ingredient_names: list[str] = []             # ["metformin", "메트포르민"]
    drug_class: Optional[str] = None             # "biguanide"
    is_combination: bool = False
    components: list[str] = []                   # 복합제 성분 normalized_name 리스트
    strength: Optional[str] = None               # raw_name에서 추출한 용량 (e.g. "500mg")


class HistoryDrug(BaseModel):
    source: Literal["emr_text", "prescription_log"]
    date: Optional[str] = None                   # "YYYY-MM-DD"
    raw_name: str
    normalized_name: str
    ingredient_code: Optional[str] = None
    ingredient_names: list[str] = []
    strength: Optional[str] = None               # "25mg"
    frequency: Optional[str] = None              # "HS", "QD"
    symptom_tags: list[str] = []                 # ["불면"]
    diagnosis_tags: list[str] = []               # ["불면증"]
    effect_status: Literal["effective", "ineffective", "unknown"] = "unknown"
    adverse_event: bool = False
    adverse_reason: Optional[str] = None         # "낙상", "혈관부종"


class HistoryMatch(BaseModel):
    history_drug: HistoryDrug
    match_type: Literal["same_diagnosis", "same_symptom", "partial", "none"]
    match_score: float                           # 0.0 ~ 1.0
    reason: str                                  # 사람이 읽을 수 있는 매칭 사유


class HistorySafetyResult(BaseModel):
    match: HistoryMatch
    is_eligible: bool
    risk_level: Literal["low", "moderate", "high", "contraindicated"]
    exclude_reasons: list[str] = []
    warnings: list[str] = []


class PromotedHistoryItem(BaseModel):
    name: str
    reason: str


class ExcludedHistoryItem(BaseModel):
    name: str
    reason: str


class HistoryPriorityInfo(BaseModel):
    promoted: list[PromotedHistoryItem] = []     # primary 최상단 배치된 과거 처방약
    excluded: list[ExcludedHistoryItem] = []     # 안전 문제로 제외된 과거 처방약
    matched_count: int = 0                       # 현재 증상/진단과 매칭된 과거 처방 수
