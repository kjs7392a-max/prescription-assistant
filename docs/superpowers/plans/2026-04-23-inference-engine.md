# Inference Engine & History System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 환자 Lab 시계열 + 부작용 이력을 우선순위 컨텍스트로 조립하여 Claude LLM이 델타(변화량)를 인지하고 성분명 기반 처방 가이드 JSON을 반환하는 추론 엔진을 구축한다.

**Architecture:** PatientLabHistory(시계열) + PrescriptionFeedback(부작용·수정이력) 2개 테이블을 신규 추가하고, `InferenceEngine` 서비스가 우선순위 순서(부작용→Lab Delta→최근처방→의사메모)로 컨텍스트를 조립해 `ClaudeProvider`를 호출한다. `BaseLLMProvider` 인터페이스로 추상화하여 향후 다른 LLM으로 교체 가능하다.

**Tech Stack:** FastAPI, SQLAlchemy 2.x async, Pydantic v2, anthropic SDK (AsyncAnthropic), PostgreSQL JSONB, pytest + pytest-asyncio, unittest.mock

---

## 파일 구조 (신규/수정)

```
app/
├── config.py                        MODIFY: anthropic_api_key 필드 추가
├── models/
│   ├── lab_history.py               CREATE: PatientLabHistory ORM
│   ├── feedback.py                  CREATE: PrescriptionFeedback ORM
│   └── __init__.py                  MODIFY: 2개 모델 임포트 추가
├── schemas/
│   ├── lab_history.py               CREATE: Pydantic 스키마
│   ├── feedback.py                  CREATE: Pydantic 스키마
│   └── inference.py                 CREATE: InferenceRequest/Response 스키마
├── crud/
│   ├── lab_history.py               CREATE: CRUD
│   └── feedback.py                  CREATE: CRUD
├── services/
│   ├── __init__.py                  CREATE: 빈 파일
│   ├── delta.py                     CREATE: Delta 계산 유틸
│   ├── llm/
│   │   ├── __init__.py              CREATE: 빈 파일
│   │   ├── base.py                  CREATE: BaseLLMProvider ABC
│   │   └── claude.py               CREATE: ClaudeProvider
│   └── inference.py                 CREATE: InferenceEngine
└── routers/
    └── inference.py                 CREATE: POST /api/v1/inference/analyze
requirements.txt                     MODIFY: anthropic 추가
.env.example                         MODIFY: ANTHROPIC_API_KEY 추가
tests/
├── test_services/
│   ├── __init__.py                  CREATE
│   ├── test_delta.py                CREATE: Delta 단위 테스트
│   └── test_inference_engine.py     CREATE: InferenceEngine 단위 테스트
└── test_routers/
    └── test_inference_router.py     CREATE: 라우터 통합 테스트
```

---

### Task 1: 의존성 및 환경 설정 업데이트

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example`
- Modify: `app/config.py`

- [ ] **Step 1: requirements.txt에 anthropic 추가**

파일 끝에 다음 줄 추가:
```
anthropic==0.40.0
```

파일 전체 내용 (수정 후):
```
fastapi==0.115.0
uvicorn[standard]==0.32.0
sqlalchemy[asyncio]==2.0.36
asyncpg==0.30.0
alembic==1.14.0
pydantic==2.10.0
pydantic-settings==2.6.0
python-dotenv==1.0.1
pytest==8.3.3
pytest-asyncio==0.24.0
httpx==0.27.2
anthropic==0.40.0
```

설치 확인:
```bash
pip install anthropic==0.40.0
```

Expected: Successfully installed anthropic

- [ ] **Step 2: .env.example에 ANTHROPIC_API_KEY 추가**

파일 전체 내용 (수정 후):
```
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/prescription_guide
TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/prescription_guide_test
APP_ENV=development
SECRET_KEY=change-me-in-production
ANTHROPIC_API_KEY=sk-ant-api03-...
```

- [ ] **Step 3: app/config.py에 anthropic_api_key 필드 추가**

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    test_database_url: str = ""
    app_env: str = "development"
    secret_key: str = "dev-secret"
    anthropic_api_key: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

settings = Settings()
```

- [ ] **Step 4: import 검증**

```bash
DATABASE_URL="postgresql+asyncpg://x:x@localhost/x" python -c "from app.config import settings; print('anthropic_api_key field:', 'anthropic_api_key' in settings.model_fields)"
```

Expected: `anthropic_api_key field: True`

- [ ] **Step 5: 커밋**

```bash
git add requirements.txt .env.example app/config.py
git commit -m "chore: add anthropic SDK dependency and API key config"
```

---

### Task 2: PatientLabHistory 모델 + 스키마 + CRUD

**Files:**
- Create: `app/models/lab_history.py`
- Create: `app/schemas/lab_history.py`
- Create: `app/crud/lab_history.py`
- Create: `tests/test_models/test_lab_history_model.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_models/test_lab_history_model.py
import pytest
from datetime import datetime
from sqlalchemy import select
from app.models.patient import PatientProfile, DiseaseFlags, LabValues
from app.models.lab_history import PatientLabHistory

@pytest.mark.asyncio
async def test_create_lab_history_snapshot(db_session):
    patient = PatientProfile(
        patient_code="PT-LAB-001",
        age=65, gender="M",
        diseases=DiseaseFlags(ckd=True).model_dump(),
        lab_values=LabValues(egfr=60.0).model_dump(),
        allergies=[],
    )
    db_session.add(patient)
    await db_session.flush()

    snap1 = PatientLabHistory(
        patient_id=patient.id,
        recorded_at=datetime(2026, 2, 1),
        lab_values={"egfr": 60.0, "creatinine": 1.2},
        source="manual",
    )
    snap2 = PatientLabHistory(
        patient_id=patient.id,
        recorded_at=datetime(2026, 3, 1),
        lab_values={"egfr": 55.0, "creatinine": 1.4},
        source="manual",
    )
    db_session.add_all([snap1, snap2])
    await db_session.commit()

    result = await db_session.execute(
        select(PatientLabHistory)
        .where(PatientLabHistory.patient_id == patient.id)
        .order_by(PatientLabHistory.recorded_at.desc())
    )
    rows = result.scalars().all()
    assert len(rows) == 2
    assert rows[0].lab_values["egfr"] == 55.0
    assert rows[1].lab_values["egfr"] == 60.0
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_models/test_lab_history_model.py -v
```

Expected: FAIL (ImportError)

- [ ] **Step 3: app/models/lab_history.py 작성**

```python
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
```

- [ ] **Step 4: app/schemas/lab_history.py 작성**

```python
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from app.models.patient import LabValues


class LabHistoryCreate(BaseModel):
    patient_id: uuid.UUID
    recorded_at: datetime
    lab_values: LabValues
    source: str = "manual"


class LabHistoryResponse(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    recorded_at: datetime
    lab_values: dict
    source: str

    model_config = {"from_attributes": True}
```

- [ ] **Step 5: app/crud/lab_history.py 작성**

```python
import uuid
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.lab_history import PatientLabHistory
from app.models.patient import PatientProfile
from app.schemas.lab_history import LabHistoryCreate


async def record_lab_snapshot(
    db: AsyncSession, data: LabHistoryCreate
) -> PatientLabHistory:
    """Lab 수치 스냅샷을 INSERT하고, PatientProfile.lab_values를 최신값으로 갱신"""
    snapshot = PatientLabHistory(
        patient_id=data.patient_id,
        recorded_at=data.recorded_at,
        lab_values=data.lab_values.model_dump(exclude_none=True),
        source=data.source,
    )
    db.add(snapshot)

    result = await db.execute(
        select(PatientProfile).where(PatientProfile.id == data.patient_id)
    )
    patient = result.scalar_one_or_none()
    if patient:
        patient.lab_values = data.lab_values.model_dump(exclude_none=True)

    await db.commit()
    await db.refresh(snapshot)
    return snapshot


async def get_recent_lab_history(
    db: AsyncSession, patient_id: uuid.UUID, limit: int = 3
) -> list[PatientLabHistory]:
    """최근 N회 Lab 기록 (최신순)"""
    result = await db.execute(
        select(PatientLabHistory)
        .where(PatientLabHistory.patient_id == patient_id)
        .order_by(PatientLabHistory.recorded_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
```

- [ ] **Step 6: 테스트 재실행 — 통과 확인**

```bash
pytest tests/test_models/test_lab_history_model.py -v
```

Expected: PASS

- [ ] **Step 7: 커밋**

```bash
git add app/models/lab_history.py app/schemas/lab_history.py app/crud/lab_history.py tests/test_models/test_lab_history_model.py
git commit -m "feat: PatientLabHistory model — append-only lab snapshot (no overwrite)"
```

---

### Task 3: PrescriptionFeedback 모델 + 스키마 + CRUD

**Files:**
- Create: `app/models/feedback.py`
- Create: `app/schemas/feedback.py`
- Create: `app/crud/feedback.py`
- Create: `tests/test_models/test_feedback_model.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_models/test_feedback_model.py
import pytest
from sqlalchemy import select
from app.models.patient import PatientProfile, DiseaseFlags, LabValues
from app.models.drug import DrugKnowledgeBase
from app.models.prescription import PrescriptionLog
from app.models.feedback import PrescriptionFeedback
import uuid

@pytest.mark.asyncio
async def test_create_adverse_event_feedback(db_session):
    patient = PatientProfile(
        patient_code="PT-FB-001", age=70, gender="F",
        diseases=DiseaseFlags(hypertension=True).model_dump(),
        lab_values=LabValues().model_dump(), allergies=[],
    )
    drug = DrugKnowledgeBase(
        generic_name_ko="에날라프릴", generic_name_en="Enalapril",
        drug_class="ACE inhibitor", indications=["고혈압"],
        contraindications={"absolute": [], "relative": []},
        standard_dosage={"initial": {"dose_mg": 5, "frequency": "BID", "route": "PO"}, "max_daily_mg": 40},
        dose_forms=["tablet"], strengths_available_mg=[5, 10],
        guideline_source="ESC 2023", guideline_year=2023,
        special_populations={}, monitoring_parameters=[],
    )
    db_session.add_all([patient, drug])
    await db_session.flush()

    log = PrescriptionLog(
        patient_id=patient.id, session_id=uuid.uuid4(), drug_id=drug.id,
        recommended_generic_name_ko="에날라프릴",
        recommended_generic_name_en="Enalapril",
        recommended_strength_mg=5.0,
        recommended_dose_description="5mg 1정",
        recommended_frequency="BID",
        clinical_rationale="고혈압 치료",
        warnings=[],
    )
    db_session.add(log)
    await db_session.flush()

    feedback = PrescriptionFeedback(
        prescription_log_id=log.id,
        patient_id=patient.id,
        feedback_type="adverse_event",
        severity="severe",
        description="혈관부종 발생",
        affected_generic_ko="에날라프릴",
        affected_generic_en="Enalapril",
        recorded_by="Dr.Kim",
    )
    db_session.add(feedback)
    await db_session.commit()
    await db_session.refresh(feedback)

    result = await db_session.execute(
        select(PrescriptionFeedback).where(PrescriptionFeedback.patient_id == patient.id)
    )
    saved = result.scalar_one()
    assert saved.feedback_type == "adverse_event"
    assert saved.severity == "severe"
    assert saved.affected_generic_en == "Enalapril"
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_models/test_feedback_model.py -v
```

Expected: FAIL (ImportError)

- [ ] **Step 3: app/models/feedback.py 작성**

```python
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
```

- [ ] **Step 4: app/schemas/feedback.py 작성**

```python
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from typing import Literal


class FeedbackCreate(BaseModel):
    prescription_log_id: uuid.UUID
    patient_id: uuid.UUID
    feedback_type: Literal["adverse_event", "physician_override", "dose_adjusted"]
    severity: Optional[Literal["mild", "moderate", "severe"]] = None
    description: str
    affected_generic_ko: str
    affected_generic_en: str
    recorded_by: Optional[str] = None


class FeedbackResponse(BaseModel):
    id: uuid.UUID
    prescription_log_id: uuid.UUID
    patient_id: uuid.UUID
    feedback_type: str
    severity: Optional[str]
    description: str
    affected_generic_ko: str
    affected_generic_en: str
    recorded_by: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 5: app/crud/feedback.py 작성**

```python
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
```

- [ ] **Step 6: 테스트 재실행 — 통과 확인**

```bash
pytest tests/test_models/test_feedback_model.py -v
```

Expected: PASS

- [ ] **Step 7: 커밋**

```bash
git add app/models/feedback.py app/schemas/feedback.py app/crud/feedback.py tests/test_models/test_feedback_model.py
git commit -m "feat: PrescriptionFeedback model for adverse events and physician overrides"
```

---

### Task 4: models/__init__.py 업데이트 (Alembic 감지)

**Files:**
- Modify: `app/models/__init__.py`

- [ ] **Step 1: app/models/__init__.py 수정**

```python
from app.models.patient import PatientProfile
from app.models.drug import DrugKnowledgeBase
from app.models.prescription import PrescriptionLog
from app.models.lab_history import PatientLabHistory
from app.models.feedback import PrescriptionFeedback

__all__ = [
    "PatientProfile",
    "DrugKnowledgeBase",
    "PrescriptionLog",
    "PatientLabHistory",
    "PrescriptionFeedback",
]
```

- [ ] **Step 2: import 검증 — 5개 테이블 감지 확인**

```bash
DATABASE_URL="postgresql+asyncpg://x:x@localhost/x" python -c "
import app.models
tables = list(app.models.PatientProfile.metadata.tables.keys())
print('Tables:', tables)
assert len(tables) == 5
print('OK: 5 tables detected')
"
```

Expected:
```
Tables: ['patient_profiles', 'drug_knowledge_base', 'prescription_logs', 'patient_lab_history', 'prescription_feedback']
OK: 5 tables detected
```

- [ ] **Step 3: 커밋**

```bash
git add app/models/__init__.py
git commit -m "feat: register PatientLabHistory and PrescriptionFeedback in models __init__"
```

---

### Task 5: LLM 추상화 레이어 (BaseLLMProvider + ClaudeProvider)

**Files:**
- Create: `app/services/__init__.py`
- Create: `app/services/llm/__init__.py`
- Create: `app/services/llm/base.py`
- Create: `app/services/llm/claude.py`
- Create: `tests/test_services/__init__.py`

- [ ] **Step 1: 디렉토리 및 빈 파일 생성**

```bash
mkdir -p app/services/llm
mkdir -p tests/test_services
touch app/services/__init__.py
touch app/services/llm/__init__.py
touch tests/test_services/__init__.py
```

- [ ] **Step 2: app/services/llm/base.py 작성**

```python
from abc import ABC, abstractmethod


class BaseLLMProvider(ABC):
    """LLM 공급자 추상 인터페이스 — ClaudeProvider 등이 구현"""

    @abstractmethod
    async def complete(self, system: str, user: str) -> str:
        """system 프롬프트와 user 메시지를 받아 LLM 응답 텍스트를 반환"""
        ...
```

- [ ] **Step 3: app/services/llm/claude.py 작성**

```python
import anthropic
from app.services.llm.base import BaseLLMProvider
from app.config import settings

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2048


class ClaudeProvider(BaseLLMProvider):
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def complete(self, system: str, user: str) -> str:
        message = await self._client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return message.content[0].text
```

- [ ] **Step 4: import 검증**

```bash
DATABASE_URL="postgresql+asyncpg://x:x@localhost/x" python -c "
from app.services.llm.base import BaseLLMProvider
from app.services.llm.claude import ClaudeProvider
import inspect
assert inspect.isabstract(BaseLLMProvider)
print('BaseLLMProvider is abstract: OK')
print('ClaudeProvider subclass:', issubclass(ClaudeProvider, BaseLLMProvider))
"
```

Expected:
```
BaseLLMProvider is abstract: OK
ClaudeProvider subclass: True
```

- [ ] **Step 5: 커밋**

```bash
git add app/services/ tests/test_services/__init__.py
git commit -m "feat: LLM abstraction layer — BaseLLMProvider + ClaudeProvider (claude-sonnet-4-6)"
```

---

### Task 6: Delta 계산 유틸리티

**Files:**
- Create: `app/services/delta.py`
- Create: `tests/test_services/test_delta.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_services/test_delta.py
import pytest
from datetime import datetime
from app.services.delta import compute_deltas, format_delta_for_prompt


def test_compute_deltas_detects_significant_egfr_drop():
    snapshots = [
        {"recorded_at": datetime(2026, 4, 1), "lab_values": {"egfr": 40.0}},
        {"recorded_at": datetime(2026, 3, 1), "lab_values": {"egfr": 55.0}},
        {"recorded_at": datetime(2026, 2, 1), "lab_values": {"egfr": 60.0}},
    ]
    deltas = compute_deltas(snapshots)
    assert len(deltas) == 2
    first = deltas[0]["deltas"]["egfr"]
    assert first["delta"] == pytest.approx(-15.0)
    assert first["significant"] is True
    assert first["direction"] == "down"


def test_compute_deltas_not_significant_for_small_change():
    snapshots = [
        {"recorded_at": datetime(2026, 4, 1), "lab_values": {"egfr": 58.0}},
        {"recorded_at": datetime(2026, 3, 1), "lab_values": {"egfr": 60.0}},
    ]
    deltas = compute_deltas(snapshots)
    assert deltas[0]["deltas"]["egfr"]["significant"] is False


def test_compute_deltas_returns_empty_for_single_snapshot():
    snapshots = [
        {"recorded_at": datetime(2026, 4, 1), "lab_values": {"egfr": 55.0}},
    ]
    assert compute_deltas(snapshots) == []


def test_format_delta_for_prompt_includes_egfr_and_warning():
    snapshots = [
        {"recorded_at": datetime(2026, 4, 1), "lab_values": {"egfr": 40.0}},
        {"recorded_at": datetime(2026, 3, 1), "lab_values": {"egfr": 60.0}},
    ]
    result = format_delta_for_prompt(snapshots)
    assert "egfr" in result
    assert "40" in result
    assert "60" in result


def test_format_delta_for_prompt_with_current_lab_prepended():
    snapshots = [
        {"recorded_at": datetime(2026, 3, 1), "lab_values": {"egfr": 55.0}},
    ]
    current = {"egfr": 40.0}
    result = format_delta_for_prompt(snapshots, current_lab=current)
    assert "40" in result
    assert "55" in result
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_services/test_delta.py -v
```

Expected: FAIL (ImportError)

- [ ] **Step 3: app/services/delta.py 작성**

```python
from typing import Optional

SIGNIFICANT_THRESHOLDS: dict[str, float] = {
    "egfr": 10.0,        # mL/min/1.73m² — 신장 기능
    "creatinine": 0.3,   # mg/dL
    "hba1c": 0.5,        # %
    "potassium": 0.5,    # mEq/L — 고칼륨혈증 위험
    "ldl": 20.0,         # mg/dL
    "bnp": 100.0,        # pg/mL — 심부전
    "nt_probnp": 300.0,  # pg/mL
}

DISPLAY_NAMES: dict[str, str] = {
    "egfr": "eGFR(mL/min)",
    "creatinine": "Creatinine(mg/dL)",
    "hba1c": "HbA1c(%)",
    "potassium": "K+(mEq/L)",
    "ldl": "LDL(mg/dL)",
    "bnp": "BNP(pg/mL)",
    "nt_probnp": "NT-proBNP(pg/mL)",
}


def compute_deltas(snapshots: list[dict]) -> list[dict]:
    """
    snapshots: 최신순 정렬된 [{recorded_at, lab_values}, ...] 리스트
    반환: 인접 시점 간 delta 목록 (인덱스 0 = 가장 최근 변화)
    """
    if len(snapshots) < 2:
        return []

    result = []
    for i in range(len(snapshots) - 1):
        current = snapshots[i]["lab_values"]
        previous = snapshots[i + 1]["lab_values"]
        entry: dict = {
            "from_date": snapshots[i + 1]["recorded_at"],
            "to_date": snapshots[i]["recorded_at"],
            "deltas": {},
        }
        for key, threshold in SIGNIFICANT_THRESHOLDS.items():
            curr_val = current.get(key)
            prev_val = previous.get(key)
            if curr_val is not None and prev_val is not None:
                delta = curr_val - prev_val
                entry["deltas"][key] = {
                    "from": prev_val,
                    "to": curr_val,
                    "delta": round(delta, 2),
                    "significant": abs(delta) >= threshold,
                    "direction": "up" if delta > 0 else "down",
                }
        result.append(entry)
    return result


def format_delta_for_prompt(
    snapshots: list[dict],
    current_lab: Optional[dict] = None,
) -> str:
    """
    Lab 시계열을 LLM 프롬프트용 텍스트 표로 변환.
    snapshots: 최신순 정렬된 DB 기록
    current_lab: 이번 진료에서 입력된 최신 수치 (있으면 맨 앞에 삽입)
    """
    all_snaps: list[dict] = list(snapshots)
    if current_lab:
        all_snaps = [{"recorded_at": "현재", "lab_values": current_lab}] + all_snaps

    if not all_snaps:
        return "Lab 수치 이력 없음"

    # 유효한 항목만
    keys = [
        k for k in SIGNIFICANT_THRESHOLDS
        if any(s["lab_values"].get(k) is not None for s in all_snaps)
    ]
    if not keys:
        return "유효한 Lab 수치 없음"

    # 시간 헤더 (오래된 것 → 최신 순으로 표시)
    headers = [
        str(s["recorded_at"])[:10] if s["recorded_at"] != "현재" else "현재"
        for s in reversed(all_snaps)
    ]
    lines = [f"| 항목 | {' | '.join(headers)} | 총변화 |"]
    lines.append("|" + "---|" * (len(all_snaps) + 2))

    for key in keys:
        vals = [s["lab_values"].get(key) for s in reversed(all_snaps)]
        non_none = [v for v in vals if v is not None]
        if len(non_none) < 2:
            continue
        total_delta = non_none[-1] - non_none[0]
        threshold = SIGNIFICANT_THRESHOLDS[key]
        if abs(total_delta) >= threshold * 2:
            flag = " ⚠️급격"
        elif abs(total_delta) >= threshold:
            flag = " ↑" if total_delta > 0 else " ↓"
        else:
            flag = ""
        val_strs = [str(v) if v is not None else "-" for v in vals]
        name = DISPLAY_NAMES.get(key, key)
        lines.append(f"| {name} | {' | '.join(val_strs)} | {total_delta:+.1f}{flag} |")

    return "\n".join(lines)
```

- [ ] **Step 4: 테스트 재실행 — 통과 확인**

```bash
pytest tests/test_services/test_delta.py -v
```

Expected: ALL PASS (5개 테스트)

- [ ] **Step 5: 커밋**

```bash
git add app/services/delta.py tests/test_services/test_delta.py
git commit -m "feat: lab delta computation util with clinical significance thresholds"
```

---

### Task 7: InferenceEngine

**Files:**
- Create: `app/schemas/inference.py`
- Create: `app/services/inference.py`
- Create: `tests/test_services/test_inference_engine.py`

- [ ] **Step 1: app/schemas/inference.py 작성**

```python
import uuid
from datetime import date
from typing import Optional
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
    risk_level: str  # "low" | "moderate" | "high"
    warnings: list[str] = []


class InferenceResponse(BaseModel):
    recommended_generics: list[RecommendedGeneric]
    contraindicated_generics: list[str]
    lab_delta_summary: str
    overall_risk: str  # "low" | "moderate" | "high" | "critical"
    physician_action_required: bool
```

- [ ] **Step 2: 실패 테스트 작성**

```python
# tests/test_services/test_inference_engine.py
import pytest
import json
import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock
from app.models.patient import PatientProfile, DiseaseFlags, LabValues
from app.models.lab_history import PatientLabHistory
from app.models.feedback import PrescriptionFeedback
from app.models.drug import DrugKnowledgeBase
from app.models.prescription import PrescriptionLog
from app.schemas.inference import InferenceRequest
from app.services.inference import InferenceEngine


def _make_llm_response(**kwargs) -> str:
    default = {
        "recommended_generics": [
            {
                "generic_name_ko": "암로디핀",
                "generic_name_en": "Amlodipine",
                "strength_mg": 5.0,
                "frequency": "QD",
                "rationale": "고혈압 1차 선택 CCB",
                "guideline_reference": "ESC/ESH 2023",
                "risk_level": "low",
                "warnings": ["부종 모니터링"],
            }
        ],
        "contraindicated_generics": [],
        "lab_delta_summary": "eGFR 안정적",
        "overall_risk": "low",
        "physician_action_required": False,
    }
    default.update(kwargs)
    return json.dumps(default)


@pytest.mark.asyncio
async def test_inference_returns_structured_response(db_session):
    patient = PatientProfile(
        patient_code="PT-INF-001", age=65, gender="M",
        diseases=DiseaseFlags(hypertension=True).model_dump(),
        lab_values=LabValues(egfr=55.0).model_dump(),
        allergies=[],
    )
    db_session.add(patient)
    await db_session.flush()

    mock_llm = AsyncMock()
    mock_llm.complete.return_value = _make_llm_response()

    engine = InferenceEngine(llm=mock_llm)
    request = InferenceRequest(
        patient_id=patient.id,
        visit_date=date.today(),
        physician_note="혈압 조절 필요",
    )
    response = await engine.analyze(db_session, request)

    assert len(response.recommended_generics) == 1
    assert response.recommended_generics[0].generic_name_en == "Amlodipine"
    assert response.overall_risk == "low"
    assert mock_llm.complete.called


@pytest.mark.asyncio
async def test_inference_extracts_contraindicated_from_adverse_events(db_session):
    patient = PatientProfile(
        patient_code="PT-INF-002", age=70, gender="F",
        diseases=DiseaseFlags(hypertension=True).model_dump(),
        lab_values=LabValues().model_dump(),
        allergies=[],
    )
    drug = DrugKnowledgeBase(
        generic_name_ko="에날라프릴", generic_name_en="Enalapril",
        drug_class="ACE inhibitor", indications=["고혈압"],
        contraindications={"absolute": [], "relative": []},
        standard_dosage={"initial": {"dose_mg": 5, "frequency": "BID", "route": "PO"}, "max_daily_mg": 40},
        dose_forms=["tablet"], strengths_available_mg=[5],
        guideline_source="ESC 2023", guideline_year=2023,
        special_populations={}, monitoring_parameters=[],
    )
    db_session.add_all([patient, drug])
    await db_session.flush()

    log = PrescriptionLog(
        patient_id=patient.id, session_id=uuid.uuid4(), drug_id=drug.id,
        recommended_generic_name_ko="에날라프릴",
        recommended_generic_name_en="Enalapril",
        recommended_strength_mg=5.0,
        recommended_dose_description="5mg 1정",
        recommended_frequency="BID",
        clinical_rationale="고혈압",
        warnings=[],
    )
    db_session.add(log)
    await db_session.flush()

    feedback = PrescriptionFeedback(
        prescription_log_id=log.id, patient_id=patient.id,
        feedback_type="adverse_event", severity="severe",
        description="혈관부종", affected_generic_ko="에날라프릴",
        affected_generic_en="Enalapril", recorded_by="Dr.Kim",
    )
    db_session.add(feedback)
    await db_session.commit()

    mock_llm = AsyncMock()
    mock_llm.complete.return_value = _make_llm_response(
        contraindicated_generics=["Enalapril"]
    )

    engine = InferenceEngine(llm=mock_llm)
    request = InferenceRequest(
        patient_id=patient.id,
        visit_date=date.today(),
        physician_note="혈압 재평가",
    )
    response = await engine.analyze(db_session, request)

    # 부작용 정보가 프롬프트에 포함되어야 함
    call_args = mock_llm.complete.call_args
    user_prompt = call_args[1]["user"] if "user" in call_args[1] else call_args[0][1]
    assert "Enalapril" in user_prompt
    assert "혈관부종" in user_prompt


@pytest.mark.asyncio
async def test_inference_includes_lab_delta_in_prompt(db_session):
    patient = PatientProfile(
        patient_code="PT-INF-003", age=60, gender="M",
        diseases=DiseaseFlags(ckd=True).model_dump(),
        lab_values=LabValues(egfr=60.0).model_dump(),
        allergies=[],
    )
    db_session.add(patient)
    await db_session.flush()

    # Lab 히스토리 2건 추가
    db_session.add(PatientLabHistory(
        patient_id=patient.id,
        recorded_at=datetime(2026, 2, 1),
        lab_values={"egfr": 60.0},
        source="manual",
    ))
    db_session.add(PatientLabHistory(
        patient_id=patient.id,
        recorded_at=datetime(2026, 3, 1),
        lab_values={"egfr": 45.0},
        source="manual",
    ))
    await db_session.commit()

    mock_llm = AsyncMock()
    mock_llm.complete.return_value = _make_llm_response(
        lab_delta_summary="eGFR: 60→45→40, 급격한 하강"
    )

    engine = InferenceEngine(llm=mock_llm)
    request = InferenceRequest(
        patient_id=patient.id,
        visit_date=date.today(),
        current_lab_values=LabValues(egfr=40.0),
        physician_note="신기능 악화 우려",
    )
    response = await engine.analyze(db_session, request)

    call_args = mock_llm.complete.call_args
    user_prompt = call_args[1]["user"] if "user" in call_args[1] else call_args[0][1]
    assert "egfr" in user_prompt.lower() or "eGFR" in user_prompt
    assert "40" in user_prompt
```

- [ ] **Step 3: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_services/test_inference_engine.py -v
```

Expected: FAIL (ImportError — app.services.inference 없음)

- [ ] **Step 4: app/services/inference.py 작성**

```python
import json
import re
from sqlalchemy.ext.asyncio import AsyncSession
from app.crud.feedback import get_patient_feedbacks
from app.crud.lab_history import get_recent_lab_history
from app.crud.prescription import get_logs_by_patient
from app.crud.patient import get_patient
from app.models.feedback import PrescriptionFeedback
from app.schemas.inference import InferenceRequest, InferenceResponse, RecommendedGeneric
from app.services.delta import format_delta_for_prompt
from app.services.llm.base import BaseLLMProvider

_SYSTEM_PROMPT = """\
당신은 의학 가이드라인 전문가입니다.
환자 데이터를 분석하여 성분명(Generic) 기반 처방 가이드를 제공합니다.
실제 처방 결정은 의사가 내리며, 당신의 역할은 가이드라인 레퍼런스 제공입니다.
상품명은 절대 사용하지 않으며 성분명과 함량만 사용합니다.

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트는 포함하지 마세요:
{
  "recommended_generics": [
    {
      "generic_name_ko": "성분명(한글)",
      "generic_name_en": "GenericName",
      "strength_mg": 숫자또는null,
      "frequency": "QD|BID|TID 등",
      "rationale": "추천 근거 (한국어)",
      "guideline_reference": "가이드라인 출처 또는 null",
      "risk_level": "low|moderate|high",
      "warnings": ["경고 문구"]
    }
  ],
  "contraindicated_generics": ["금기 성분명"],
  "lab_delta_summary": "주요 Lab 변화 요약 (한국어)",
  "overall_risk": "low|moderate|high|critical",
  "physician_action_required": true또는false
}"""


class InferenceEngine:
    def __init__(self, llm: BaseLLMProvider) -> None:
        self._llm = llm

    async def analyze(
        self, db: AsyncSession, request: InferenceRequest
    ) -> InferenceResponse:
        # Priority 1: 부작용·수정 이력 조회
        feedbacks = await get_patient_feedbacks(db, request.patient_id)

        # Priority 2: Lab 시계열 (최근 3회)
        lab_history = await get_recent_lab_history(db, request.patient_id, limit=3)

        # Priority 3: 최근 처방 이력 (최근 3건)
        recent_logs = (await get_logs_by_patient(db, request.patient_id))[:3]

        # 환자 현재 프로파일
        patient = await get_patient(db, request.patient_id)

        user_prompt = self._build_user_prompt(
            patient=patient,
            feedbacks=feedbacks,
            lab_history=lab_history,
            recent_logs=recent_logs,
            request=request,
        )
        raw = await self._llm.complete(system=_SYSTEM_PROMPT, user=user_prompt)
        return self._parse_response(raw)

    def _build_user_prompt(
        self, patient, feedbacks, lab_history, recent_logs, request: InferenceRequest
    ) -> str:
        lines: list[str] = []

        # 환자 기본 정보
        lines.append("## 환자 기본 정보")
        if patient:
            lines.append(f"- 나이/성별: {patient.age}세 / {patient.gender}")
            active_diseases = [k for k, v in patient.diseases.items() if v is True]
            if active_diseases:
                lines.append(f"- 현재 질환: {', '.join(active_diseases)}")
            if patient.allergies:
                lines.append(f"- 알레르기: {', '.join(patient.allergies)}")
        if request.disease_updates:
            updates = [k for k, v in request.disease_updates.model_dump().items() if v is True]
            if updates:
                lines.append(f"- 이번 진료 질환 추가: {', '.join(updates)}")
        lines.append("")

        # Priority 1: 부작용·금기 이력
        adverse = [f for f in feedbacks if f.feedback_type == "adverse_event"]
        overrides = [f for f in feedbacks if f.feedback_type == "physician_override"]
        if adverse or overrides:
            lines.append("## ⚠️ 부작용·금기 이력 (최우선 고려)")
            for f in adverse:
                sev = f" ({f.severity})" if f.severity else ""
                lines.append(
                    f"- [부작용{sev}] {f.affected_generic_ko}({f.affected_generic_en})"
                    f" → {f.description} ▶ 이 성분 추천 금지"
                )
            for f in overrides:
                lines.append(
                    f"- [의사수정] {f.affected_generic_ko}({f.affected_generic_en})"
                    f" → {f.description}"
                )
            lines.append("")

        # Priority 2: Lab 시계열 + Delta
        lines.append("## Lab 수치 시계열 (Delta)")
        current_lab = (
            request.current_lab_values.model_dump(exclude_none=True)
            if request.current_lab_values
            else None
        )
        snapshots = [
            {"recorded_at": h.recorded_at, "lab_values": h.lab_values}
            for h in lab_history
        ]
        lines.append(format_delta_for_prompt(snapshots, current_lab=current_lab))
        lines.append("")

        # Priority 3: 최근 처방 이력
        if recent_logs:
            lines.append("## 최근 처방 이력 (최근 3건)")
            for i, log in enumerate(recent_logs, 1):
                lines.append(
                    f"{i}. [{log.created_at.strftime('%Y-%m-%d')}]"
                    f" {log.recommended_generic_name_ko}"
                    f" {log.recommended_strength_mg}mg {log.recommended_frequency}"
                )
                if log.physician_notes:
                    lines.append(f"   메모: {log.physician_notes}")
            lines.append("")

        # 의사 메모
        lines.append("## 의사 메모 (이번 진료)")
        lines.append(request.physician_note)
        lines.append("")
        lines.append("위 정보를 바탕으로 JSON 형식으로 처방 가이드를 제공하세요.")

        return "\n".join(lines)

    def _parse_response(self, raw: str) -> InferenceResponse:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError(f"LLM이 유효한 JSON을 반환하지 않았습니다: {raw[:300]}")
        data = json.loads(match.group())
        return InferenceResponse(
            recommended_generics=[
                RecommendedGeneric(**g) for g in data.get("recommended_generics", [])
            ],
            contraindicated_generics=data.get("contraindicated_generics", []),
            lab_delta_summary=data.get("lab_delta_summary", ""),
            overall_risk=data.get("overall_risk", "moderate"),
            physician_action_required=data.get("physician_action_required", True),
        )
```

- [ ] **Step 5: 테스트 재실행 — 통과 확인**

```bash
pytest tests/test_services/test_inference_engine.py -v
```

Expected: ALL PASS (3개 테스트)

- [ ] **Step 6: 커밋**

```bash
git add app/schemas/inference.py app/services/inference.py tests/test_services/test_inference_engine.py
git commit -m "feat: InferenceEngine — priority-ordered context assembly + LLM call + JSON parsing"
```

---

### Task 8: Inference API 라우터 + main.py 연결

**Files:**
- Create: `app/routers/inference.py`
- Modify: `app/main.py`
- Create: `tests/test_routers/test_inference_router.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_routers/test_inference_router.py
import pytest
import json
import uuid
from unittest.mock import AsyncMock, patch
from app.models.patient import PatientProfile, DiseaseFlags, LabValues


@pytest.mark.asyncio
async def test_analyze_endpoint_returns_200(client, db_session):
    patient = PatientProfile(
        patient_code="PT-API-001", age=65, gender="M",
        diseases=DiseaseFlags(hypertension=True).model_dump(),
        lab_values=LabValues(egfr=55.0).model_dump(),
        allergies=[],
    )
    db_session.add(patient)
    await db_session.commit()

    mock_response_json = json.dumps({
        "recommended_generics": [
            {
                "generic_name_ko": "암로디핀",
                "generic_name_en": "Amlodipine",
                "strength_mg": 5.0,
                "frequency": "QD",
                "rationale": "고혈압 1차 CCB",
                "guideline_reference": "ESC/ESH 2023",
                "risk_level": "low",
                "warnings": [],
            }
        ],
        "contraindicated_generics": [],
        "lab_delta_summary": "eGFR 안정적",
        "overall_risk": "low",
        "physician_action_required": False,
    })

    with patch("app.routers.inference.ClaudeProvider") as MockProvider:
        mock_instance = AsyncMock()
        mock_instance.complete.return_value = mock_response_json
        MockProvider.return_value = mock_instance

        res = await client.post(
            "/api/v1/inference/analyze",
            json={
                "patient_id": str(patient.id),
                "visit_date": "2026-04-23",
                "physician_note": "혈압 조절 필요",
            },
        )

    assert res.status_code == 200
    data = res.json()
    assert len(data["recommended_generics"]) == 1
    assert data["recommended_generics"][0]["generic_name_en"] == "Amlodipine"
    assert data["overall_risk"] == "low"


@pytest.mark.asyncio
async def test_analyze_endpoint_returns_404_for_unknown_patient(client):
    with patch("app.routers.inference.ClaudeProvider"):
        res = await client.post(
            "/api/v1/inference/analyze",
            json={
                "patient_id": str(uuid.uuid4()),
                "visit_date": "2026-04-23",
                "physician_note": "테스트",
            },
        )
    assert res.status_code == 404
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_routers/test_inference_router.py -v
```

Expected: FAIL (라우터 없음)

- [ ] **Step 3: app/routers/inference.py 작성**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.crud.patient import get_patient
from app.schemas.inference import InferenceRequest, InferenceResponse
from app.services.inference import InferenceEngine
from app.services.llm.claude import ClaudeProvider

router = APIRouter(prefix="/api/v1/inference", tags=["inference"])


@router.post("/analyze", response_model=InferenceResponse)
async def analyze(
    request: InferenceRequest,
    db: AsyncSession = Depends(get_db),
) -> InferenceResponse:
    patient = await get_patient(db, request.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    engine = InferenceEngine(llm=ClaudeProvider())
    return await engine.analyze(db, request)
```

- [ ] **Step 4: app/main.py 수정 — inference 라우터 추가**

```python
from fastapi import FastAPI
from app.routers import patients, drugs, prescriptions, inference

app = FastAPI(
    title="처방 가이드 시스템",
    description="성분명(Generic) 기반 범용 처방 레퍼런스 API — 실제 처방은 의사가 EMR에 직접 입력",
    version="0.2.0",
)

app.include_router(patients.router)
app.include_router(drugs.router)
app.include_router(prescriptions.router)
app.include_router(inference.router)

@app.get("/")
async def health_check():
    return {"status": "ok", "service": "prescription-guide", "version": "0.2.0"}
```

- [ ] **Step 5: 테스트 재실행 — 통과 확인**

```bash
pytest tests/test_routers/test_inference_router.py -v
```

Expected: ALL PASS (2개 테스트)

- [ ] **Step 6: 전체 테스트 실행**

```bash
pytest tests/ -v --tb=short
```

Expected: 모든 테스트 PASS (ImportError, DB 연결 오류 제외하고 실제 로직 테스트는 모두 통과)

- [ ] **Step 7: 커밋**

```bash
git add app/routers/inference.py app/main.py tests/test_routers/test_inference_router.py
git commit -m "feat: POST /api/v1/inference/analyze endpoint — inference engine v0.2.0"
```

---

## 자가 검토 (Spec Self-Review)

### 스펙 커버리지 확인

| 요구사항 | Task |
|---|---|
| patient_lab_history 테이블 | Task 2 |
| prescription_feedback 테이블 | Task 3 |
| BaseLLMProvider 추상 클래스 | Task 5 |
| ClaudeProvider (claude-sonnet-4-6) | Task 5 |
| InferenceEngine — Priority 1: feedback 금기 식별 | Task 7 |
| InferenceEngine — Priority 2: Lab Delta 계산 | Task 6 + Task 7 |
| InferenceEngine — Priority 3: 의사 메모 + 컨텍스트 조립 | Task 7 |
| InferenceEngine — Priority 4: LLM 호출 + JSON 파싱 | Task 7 |
| POST /api/v1/inference/analyze | Task 8 |
| Lab 스냅샷 CRUD (덮어쓰기 없음) | Task 2 (record_lab_snapshot) |
| 부작용 이력 CRUD | Task 3 |
| models/__init__.py Alembic 감지 | Task 4 |
| anthropic SDK 의존성 | Task 1 |

**갭 없음 — 모든 요구사항 커버됨.**

### 타입 일관성 확인

- `get_patient_feedbacks` → Task 3에서 정의, Task 7 InferenceEngine에서 임포트 ✅
- `get_recent_lab_history` → Task 2에서 정의, Task 7에서 임포트 ✅
- `format_delta_for_prompt` → Task 6에서 정의, Task 7에서 임포트 ✅
- `InferenceRequest` / `InferenceResponse` → Task 7 schemas에서 정의, Task 8 라우터에서 사용 ✅
- `ClaudeProvider` → Task 5에서 정의, Task 8 라우터에서 임포트 ✅
