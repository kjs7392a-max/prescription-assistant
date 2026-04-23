# 처방 가이드 시스템 (Prescription Guide System) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI 보조 범용 처방 가이드 시스템 — 성분명(Generic) 기반 약물 지식 DB와 환자 프로파일을 연계하여 의사가 EMR에 입력할 표준 처방 레퍼런스를 제공하는 FastAPI 백엔드를 구축한다.

**Architecture:** PostgreSQL + SQLAlchemy ORM으로 Patient_Profile / Drug_Knowledge_Base / Prescription_Log 3개 핵심 테이블을 설계하고, FastAPI 라우터 레이어에서 CRUD를 노출한다. Alembic으로 스키마 마이그레이션을 관리하며, 상품명은 일절 저장하지 않고 성분명(generic_name) + 함량(strength)만 관리한다.

**Tech Stack:** Python 3.11+, FastAPI 0.115+, SQLAlchemy 2.x (async), asyncpg, Alembic, Pydantic v2, PostgreSQL 16, pytest + pytest-asyncio, python-dotenv

---

## 파일 구조

```
처방보조 프로젝트/
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI 앱 진입점
│   ├── config.py                   # Settings (DB URL, 환경변수)
│   ├── database.py                 # async SQLAlchemy engine + session
│   ├── models/
│   │   ├── __init__.py
│   │   ├── patient.py              # PatientProfile ORM 모델
│   │   ├── drug.py                 # DrugKnowledgeBase ORM 모델
│   │   └── prescription.py        # PrescriptionLog ORM 모델
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── patient.py              # Pydantic 입출력 스키마 (환자)
│   │   ├── drug.py                 # Pydantic 입출력 스키마 (약물)
│   │   └── prescription.py        # Pydantic 입출력 스키마 (처방 로그)
│   ├── crud/
│   │   ├── __init__.py
│   │   ├── patient.py              # Patient CRUD
│   │   ├── drug.py                 # Drug CRUD + 검색
│   │   └── prescription.py        # Prescription Log CRUD
│   └── routers/
│       ├── __init__.py
│       ├── patients.py             # /patients 엔드포인트
│       ├── drugs.py                # /drugs 엔드포인트
│       └── prescriptions.py       # /prescriptions 엔드포인트
├── migrations/
│   ├── env.py                      # Alembic 환경 설정
│   └── versions/
│       └── (자동 생성)
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # pytest fixtures (테스트 DB)
│   ├── test_models/
│   │   ├── test_patient_model.py
│   │   ├── test_drug_model.py
│   │   └── test_prescription_model.py
│   └── test_routers/
│       ├── test_patients_router.py
│       ├── test_drugs_router.py
│       └── test_prescriptions_router.py
├── alembic.ini
├── requirements.txt
├── .env.example
└── README.md
```

---

### Task 1: 프로젝트 초기 설정 (환경, 의존성)

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `app/__init__.py`
- Create: `app/config.py`

- [ ] **Step 1: requirements.txt 작성**

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
```

파일 저장 후 실행:
```bash
pip install -r requirements.txt
```

- [ ] **Step 2: .env.example 작성**

```
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/prescription_guide
TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/prescription_guide_test
APP_ENV=development
SECRET_KEY=change-me-in-production
```

- [ ] **Step 3: app/config.py 작성**

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    test_database_url: str = ""
    app_env: str = "development"
    secret_key: str = "dev-secret"

    class Config:
        env_file = ".env"

settings = Settings()
```

- [ ] **Step 4: 디렉토리 구조 및 빈 __init__.py 생성**

```bash
mkdir -p app/models app/schemas app/crud app/routers
mkdir -p migrations/versions
mkdir -p tests/test_models tests/test_routers
touch app/__init__.py app/models/__init__.py app/schemas/__init__.py
touch app/crud/__init__.py app/routers/__init__.py
touch tests/__init__.py tests/test_models/__init__.py tests/test_routers/__init__.py
```

- [ ] **Step 5: 커밋**

```bash
git init
git add .
git commit -m "chore: initial project scaffolding and dependency setup"
```

---

### Task 2: 데이터베이스 연결 (async SQLAlchemy)

**Files:**
- Create: `app/database.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: 실패 테스트 작성 (`tests/conftest.py`)**

```python
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.database import Base, get_db
from app.main import app
from httpx import AsyncClient, ASGITransport
import os

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:password@localhost:5432/prescription_guide_test"
)

@pytest_asyncio.fixture(scope="session")
async def engine():
    eng = create_async_engine(TEST_DB_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()

@pytest_asyncio.fixture
async def db_session(engine):
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()

@pytest_asyncio.fixture
async def client(engine):
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def override_get_db():
        async with async_session() as session:
            yield session
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
```

- [ ] **Step 2: app/database.py 작성**

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
```

- [ ] **Step 3: app/main.py 기본 틀 작성 (테스트 통과용)**

```python
from fastapi import FastAPI

app = FastAPI(
    title="처방 가이드 시스템",
    description="성분명 기반 범용 처방 레퍼런스 API",
    version="0.1.0",
)

@app.get("/")
async def health_check():
    return {"status": "ok", "service": "prescription-guide"}
```

- [ ] **Step 4: 테스트 실행 — DB 연결 확인**

```bash
pytest tests/conftest.py -v
```

Expected: 픽스처가 세션 없이 통과 (import 오류 없음)

- [ ] **Step 5: 커밋**

```bash
git add app/database.py app/main.py app/config.py tests/conftest.py
git commit -m "feat: async SQLAlchemy engine and test DB fixture"
```

---

### Task 3: PatientProfile 모델 & 스키마

**Files:**
- Create: `app/models/patient.py`
- Create: `app/schemas/patient.py`
- Create: `tests/test_models/test_patient_model.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_models/test_patient_model.py
import pytest
from sqlalchemy import select
from app.models.patient import PatientProfile, DiseaseFlags, LabValues

@pytest.mark.asyncio
async def test_create_patient_profile(db_session):
    patient = PatientProfile(
        patient_code="PT-001",
        age=65,
        gender="M",
        weight_kg=72.0,
        height_cm=170.0,
        diseases=DiseaseFlags(
            hypertension=True,
            diabetes_type2=True,
            ckd=True,
            ckd_stage=3,
        ).model_dump(),
        lab_values=LabValues(
            creatinine=1.8,
            egfr=38.0,
            hba1c=7.2,
            fasting_glucose=145.0,
            ldl=112.0,
            hdl=45.0,
            total_cholesterol=198.0,
        ).model_dump(),
        allergies=["penicillin"],
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    result = await db_session.execute(
        select(PatientProfile).where(PatientProfile.patient_code == "PT-001")
    )
    saved = result.scalar_one()
    assert saved.diseases["hypertension"] is True
    assert saved.lab_values["egfr"] == 38.0
    assert "penicillin" in saved.allergies
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_models/test_patient_model.py -v
```

Expected: FAIL (ImportError — 모델 없음)

- [ ] **Step 3: app/models/patient.py 작성**

```python
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
```

- [ ] **Step 4: app/schemas/patient.py 작성**

```python
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from app.models.patient import DiseaseFlags, LabValues


class PatientProfileCreate(BaseModel):
    patient_code: str
    age: int
    gender: str
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None
    diseases: DiseaseFlags = DiseaseFlags()
    lab_values: LabValues = LabValues()
    allergies: list[str] = []
    current_medications: Optional[dict] = None
    clinical_notes: Optional[str] = None


class PatientProfileUpdate(BaseModel):
    age: Optional[int] = None
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None
    diseases: Optional[DiseaseFlags] = None
    lab_values: Optional[LabValues] = None
    allergies: Optional[list[str]] = None
    current_medications: Optional[dict] = None
    clinical_notes: Optional[str] = None


class PatientProfileResponse(BaseModel):
    id: uuid.UUID
    patient_code: str
    age: int
    gender: str
    weight_kg: Optional[float]
    height_cm: Optional[float]
    diseases: dict
    lab_values: dict
    allergies: list[str]
    current_medications: Optional[dict]
    clinical_notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 5: 테스트 재실행 — 통과 확인**

```bash
pytest tests/test_models/test_patient_model.py -v
```

Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add app/models/patient.py app/schemas/patient.py tests/test_models/test_patient_model.py
git commit -m "feat: PatientProfile model with 15 disease flags and lab values (JSONB)"
```

---

### Task 4: DrugKnowledgeBase 모델 & 스키마

**Files:**
- Create: `app/models/drug.py`
- Create: `app/schemas/drug.py`
- Create: `tests/test_models/test_drug_model.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_models/test_drug_model.py
import pytest
from sqlalchemy import select
from app.models.drug import DrugKnowledgeBase

@pytest.mark.asyncio
async def test_create_drug(db_session):
    drug = DrugKnowledgeBase(
        generic_name_ko="메트포르민",
        generic_name_en="Metformin",
        drug_class="Biguanide",
        indications=["2형 당뇨병"],
        contraindications={
            "absolute": ["eGFR < 30", "급성/만성 대사성산증"],
            "relative": ["eGFR 30-45 (모니터링 필요)", "조영제 투여 전 48시간"],
        },
        standard_dosage={
            "initial": {"dose_mg": 500, "frequency": "BID", "route": "PO"},
            "maintenance": {"dose_mg": 1000, "frequency": "BID", "route": "PO"},
            "max_daily_mg": 2550,
        },
        dose_forms=["tablet", "XR-tablet"],
        strengths_available_mg=[500, 850, 1000],
        guideline_source="ADA Standards of Medical Care in Diabetes 2024",
        guideline_year=2024,
        special_populations={
            "renal": {
                "egfr_30_45": "용량 감량 검토, 면밀한 모니터링",
                "egfr_lt_30": "금기",
            },
            "hepatic": "간기능 장애 시 사용 주의",
            "elderly": "신기능 저하 가능성 고려, 정기적 eGFR 모니터링",
            "pregnancy": "2형 당뇨 임신 시 사용 가능 (전문의 판단)",
        },
        monitoring_parameters=["eGFR (6개월마다)", "HbA1c (3개월마다)", "비타민B12 (장기 투여)"],
    )
    db_session.add(drug)
    await db_session.commit()
    await db_session.refresh(drug)

    result = await db_session.execute(
        select(DrugKnowledgeBase).where(DrugKnowledgeBase.generic_name_en == "Metformin")
    )
    saved = result.scalar_one()
    assert saved.generic_name_ko == "메트포르민"
    assert saved.standard_dosage["max_daily_mg"] == 2550
    assert 500 in saved.strengths_available_mg
    assert saved.guideline_year == 2024
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_models/test_drug_model.py -v
```

Expected: FAIL (ImportError)

- [ ] **Step 3: app/models/drug.py 작성**

```python
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
```

- [ ] **Step 4: app/schemas/drug.py 작성**

```python
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class DrugKnowledgeBaseCreate(BaseModel):
    generic_name_ko: str
    generic_name_en: str
    drug_class: str
    indications: list[str]
    contraindications: dict                # {"absolute": [...], "relative": [...]}
    standard_dosage: dict                  # {"initial": {...}, "maintenance": {...}, "max_daily_mg": N}
    dose_forms: list[str]
    strengths_available_mg: list[float]
    guideline_source: str
    guideline_year: int
    guideline_url: Optional[str] = None
    special_populations: dict = {}
    drug_interactions: list[str] = []
    monitoring_parameters: list[str] = []
    clinical_notes: Optional[str] = None


class DrugKnowledgeBaseUpdate(BaseModel):
    drug_class: Optional[str] = None
    indications: Optional[list[str]] = None
    contraindications: Optional[dict] = None
    standard_dosage: Optional[dict] = None
    dose_forms: Optional[list[str]] = None
    strengths_available_mg: Optional[list[float]] = None
    guideline_source: Optional[str] = None
    guideline_year: Optional[int] = None
    guideline_url: Optional[str] = None
    special_populations: Optional[dict] = None
    drug_interactions: Optional[list[str]] = None
    monitoring_parameters: Optional[list[str]] = None
    clinical_notes: Optional[str] = None


class DrugKnowledgeBaseResponse(BaseModel):
    id: uuid.UUID
    generic_name_ko: str
    generic_name_en: str
    drug_class: str
    indications: list[str]
    contraindications: dict
    standard_dosage: dict
    dose_forms: list[str]
    strengths_available_mg: list
    guideline_source: str
    guideline_year: int
    guideline_url: Optional[str]
    special_populations: dict
    drug_interactions: list[str]
    monitoring_parameters: list[str]
    clinical_notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 5: 테스트 재실행 — 통과 확인**

```bash
pytest tests/test_models/test_drug_model.py -v
```

Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add app/models/drug.py app/schemas/drug.py tests/test_models/test_drug_model.py
git commit -m "feat: DrugKnowledgeBase model — generic name + dosage schema (no brand names)"
```

---

### Task 5: PrescriptionLog 모델 & 스키마

**Files:**
- Create: `app/models/prescription.py`
- Create: `app/schemas/prescription.py`
- Modify: `app/models/__init__.py`
- Create: `tests/test_models/test_prescription_model.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_models/test_prescription_model.py
import pytest
import uuid
from sqlalchemy import select
from app.models.patient import PatientProfile, DiseaseFlags, LabValues
from app.models.drug import DrugKnowledgeBase
from app.models.prescription import PrescriptionLog

@pytest.mark.asyncio
async def test_create_prescription_log(db_session):
    patient = PatientProfile(
        patient_code="PT-PRESC-001",
        age=70,
        gender="F",
        diseases=DiseaseFlags(hypertension=True, heart_failure=True).model_dump(),
        lab_values=LabValues(egfr=55.0, bnp=380.0).model_dump(),
        allergies=[],
    )
    drug = DrugKnowledgeBase(
        generic_name_ko="에날라프릴",
        generic_name_en="Enalapril",
        drug_class="ACE inhibitor",
        indications=["고혈압", "심부전"],
        contraindications={"absolute": ["임신", "혈관부종 과거력"], "relative": []},
        standard_dosage={"initial": {"dose_mg": 2.5, "frequency": "BID", "route": "PO"},
                         "maintenance": {"dose_mg": 10, "frequency": "BID", "route": "PO"},
                         "max_daily_mg": 40},
        dose_forms=["tablet"],
        strengths_available_mg=[2.5, 5, 10, 20],
        guideline_source="ESC Heart Failure Guidelines 2023",
        guideline_year=2023,
        special_populations={"renal": {"egfr_30_60": "초기 2.5mg, 신중 용량 조절"}},
        monitoring_parameters=["혈압", "eGFR", "혈청 칼륨"],
    )
    db_session.add_all([patient, drug])
    await db_session.flush()

    session_id = uuid.uuid4()
    log = PrescriptionLog(
        patient_id=patient.id,
        session_id=session_id,
        drug_id=drug.id,
        recommended_generic_name_ko="에날라프릴",
        recommended_generic_name_en="Enalapril",
        recommended_strength_mg=2.5,
        recommended_dose_description="2.5mg 1정",
        recommended_frequency="1일 2회 (BID)",
        recommended_duration_days=30,
        clinical_rationale="심부전 동반 고혈압 — ACE억제제 1차 선택, eGFR 55로 초기 저용량 시작",
        guideline_reference="ESC Heart Failure Guidelines 2023 §7.2",
        warnings=["첫 투여 후 저혈압 모니터링", "칼륨 수치 추적 필요"],
        physician_notes="혈압 및 신기능 2주 후 재확인 권고",
    )
    db_session.add(log)
    await db_session.commit()
    await db_session.refresh(log)

    result = await db_session.execute(
        select(PrescriptionLog).where(PrescriptionLog.session_id == session_id)
    )
    saved = result.scalar_one()
    assert saved.recommended_strength_mg == 2.5
    assert "ACE억제제" in saved.clinical_rationale
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_models/test_prescription_model.py -v
```

Expected: FAIL (ImportError)

- [ ] **Step 3: app/models/prescription.py 작성**

```python
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, Float, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
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
```

- [ ] **Step 4: app/models/__init__.py — 모든 모델 임포트 (Alembic 감지용)**

```python
from app.models.patient import PatientProfile
from app.models.drug import DrugKnowledgeBase
from app.models.prescription import PrescriptionLog

__all__ = ["PatientProfile", "DrugKnowledgeBase", "PrescriptionLog"]
```

- [ ] **Step 5: app/schemas/prescription.py 작성**

```python
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class PrescriptionLogCreate(BaseModel):
    patient_id: uuid.UUID
    session_id: uuid.UUID
    drug_id: uuid.UUID
    recommended_generic_name_ko: str
    recommended_generic_name_en: str
    recommended_strength_mg: Optional[float] = None
    recommended_dose_description: str
    recommended_frequency: str
    recommended_duration_days: Optional[int] = None
    clinical_rationale: str
    guideline_reference: Optional[str] = None
    warnings: list[str] = []
    physician_notes: Optional[str] = None


class PrescriptionLogResponse(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    session_id: uuid.UUID
    drug_id: uuid.UUID
    recommended_generic_name_ko: str
    recommended_generic_name_en: str
    recommended_strength_mg: Optional[float]
    recommended_dose_description: str
    recommended_frequency: str
    recommended_duration_days: Optional[int]
    clinical_rationale: str
    guideline_reference: Optional[str]
    warnings: list[str]
    physician_notes: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 6: 테스트 재실행 — 통과 확인**

```bash
pytest tests/test_models/ -v
```

Expected: ALL PASS (3개 모델 테스트)

- [ ] **Step 7: 커밋**

```bash
git add app/models/ app/schemas/prescription.py tests/test_models/test_prescription_model.py
git commit -m "feat: PrescriptionLog model with FK to patient and drug (generic-name-only)"
```

---

### Task 6: CRUD 레이어

**Files:**
- Create: `app/crud/patient.py`
- Create: `app/crud/drug.py`
- Create: `app/crud/prescription.py`

- [ ] **Step 1: app/crud/patient.py 작성**

```python
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.patient import PatientProfile
from app.schemas.patient import PatientProfileCreate, PatientProfileUpdate


async def create_patient(db: AsyncSession, data: PatientProfileCreate) -> PatientProfile:
    patient = PatientProfile(
        patient_code=data.patient_code,
        age=data.age,
        gender=data.gender,
        weight_kg=data.weight_kg,
        height_cm=data.height_cm,
        diseases=data.diseases.model_dump(),
        lab_values=data.lab_values.model_dump(),
        allergies=data.allergies,
        current_medications=data.current_medications,
        clinical_notes=data.clinical_notes,
    )
    db.add(patient)
    await db.commit()
    await db.refresh(patient)
    return patient


async def get_patient(db: AsyncSession, patient_id: uuid.UUID) -> PatientProfile | None:
    result = await db.execute(select(PatientProfile).where(PatientProfile.id == patient_id))
    return result.scalar_one_or_none()


async def get_patient_by_code(db: AsyncSession, patient_code: str) -> PatientProfile | None:
    result = await db.execute(
        select(PatientProfile).where(PatientProfile.patient_code == patient_code)
    )
    return result.scalar_one_or_none()


async def list_patients(db: AsyncSession, skip: int = 0, limit: int = 50) -> list[PatientProfile]:
    result = await db.execute(select(PatientProfile).offset(skip).limit(limit))
    return list(result.scalars().all())


async def update_patient(
    db: AsyncSession, patient: PatientProfile, data: PatientProfileUpdate
) -> PatientProfile:
    for field, value in data.model_dump(exclude_none=True).items():
        if field == "diseases":
            setattr(patient, field, value.model_dump() if hasattr(value, "model_dump") else value)
        elif field == "lab_values":
            setattr(patient, field, value.model_dump() if hasattr(value, "model_dump") else value)
        else:
            setattr(patient, field, value)
    await db.commit()
    await db.refresh(patient)
    return patient
```

- [ ] **Step 2: app/crud/drug.py 작성**

```python
import uuid
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.drug import DrugKnowledgeBase
from app.schemas.drug import DrugKnowledgeBaseCreate, DrugKnowledgeBaseUpdate


async def create_drug(db: AsyncSession, data: DrugKnowledgeBaseCreate) -> DrugKnowledgeBase:
    drug = DrugKnowledgeBase(**data.model_dump())
    db.add(drug)
    await db.commit()
    await db.refresh(drug)
    return drug


async def get_drug(db: AsyncSession, drug_id: uuid.UUID) -> DrugKnowledgeBase | None:
    result = await db.execute(select(DrugKnowledgeBase).where(DrugKnowledgeBase.id == drug_id))
    return result.scalar_one_or_none()


async def search_drugs(db: AsyncSession, query: str) -> list[DrugKnowledgeBase]:
    """성분명(한글/영문) 또는 약물 분류로 검색"""
    result = await db.execute(
        select(DrugKnowledgeBase).where(
            or_(
                DrugKnowledgeBase.generic_name_ko.ilike(f"%{query}%"),
                DrugKnowledgeBase.generic_name_en.ilike(f"%{query}%"),
                DrugKnowledgeBase.drug_class.ilike(f"%{query}%"),
            )
        )
    )
    return list(result.scalars().all())


async def list_drugs(db: AsyncSession, skip: int = 0, limit: int = 100) -> list[DrugKnowledgeBase]:
    result = await db.execute(select(DrugKnowledgeBase).offset(skip).limit(limit))
    return list(result.scalars().all())


async def update_drug(
    db: AsyncSession, drug: DrugKnowledgeBase, data: DrugKnowledgeBaseUpdate
) -> DrugKnowledgeBase:
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(drug, field, value)
    await db.commit()
    await db.refresh(drug)
    return drug
```

- [ ] **Step 3: app/crud/prescription.py 작성**

```python
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.prescription import PrescriptionLog
from app.schemas.prescription import PrescriptionLogCreate


async def create_prescription_log(
    db: AsyncSession, data: PrescriptionLogCreate
) -> PrescriptionLog:
    log = PrescriptionLog(**data.model_dump())
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


async def get_logs_by_patient(
    db: AsyncSession, patient_id: uuid.UUID
) -> list[PrescriptionLog]:
    result = await db.execute(
        select(PrescriptionLog)
        .where(PrescriptionLog.patient_id == patient_id)
        .order_by(PrescriptionLog.created_at.desc())
    )
    return list(result.scalars().all())


async def get_logs_by_session(
    db: AsyncSession, session_id: uuid.UUID
) -> list[PrescriptionLog]:
    result = await db.execute(
        select(PrescriptionLog).where(PrescriptionLog.session_id == session_id)
    )
    return list(result.scalars().all())
```

- [ ] **Step 4: 커밋**

```bash
git add app/crud/
git commit -m "feat: CRUD layer for patient, drug, and prescription log"
```

---

### Task 7: FastAPI 라우터

**Files:**
- Create: `app/routers/patients.py`
- Create: `app/routers/drugs.py`
- Create: `app/routers/prescriptions.py`
- Modify: `app/main.py`

- [ ] **Step 1: 실패 테스트 작성 (`tests/test_routers/test_drugs_router.py`)**

```python
# tests/test_routers/test_drugs_router.py
import pytest

@pytest.mark.asyncio
async def test_create_and_search_drug(client):
    payload = {
        "generic_name_ko": "암로디핀",
        "generic_name_en": "Amlodipine",
        "drug_class": "Calcium Channel Blocker",
        "indications": ["고혈압", "안정형 협심증"],
        "contraindications": {"absolute": ["심인성 쇼크"], "relative": []},
        "standard_dosage": {
            "initial": {"dose_mg": 5, "frequency": "QD", "route": "PO"},
            "maintenance": {"dose_mg": 5, "frequency": "QD", "route": "PO"},
            "max_daily_mg": 10,
        },
        "dose_forms": ["tablet"],
        "strengths_available_mg": [2.5, 5, 10],
        "guideline_source": "ESC/ESH Hypertension Guidelines 2023",
        "guideline_year": 2023,
        "special_populations": {
            "elderly": "5mg으로 시작, 저혈압 모니터링",
            "hepatic": "중증 간장애 시 저용량 시작",
        },
        "monitoring_parameters": ["혈압", "부종"],
    }
    res = await client.post("/drugs/", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["generic_name_en"] == "Amlodipine"

    search_res = await client.get("/drugs/search?q=암로디핀")
    assert search_res.status_code == 200
    results = search_res.json()
    assert len(results) >= 1
    assert results[0]["generic_name_ko"] == "암로디핀"
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_routers/test_drugs_router.py -v
```

Expected: FAIL (404 또는 라우터 없음)

- [ ] **Step 3: app/routers/patients.py 작성**

```python
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.patient import PatientProfileCreate, PatientProfileUpdate, PatientProfileResponse
from app.crud import patient as patient_crud

router = APIRouter(prefix="/patients", tags=["patients"])


@router.post("/", response_model=PatientProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_patient(data: PatientProfileCreate, db: AsyncSession = Depends(get_db)):
    existing = await patient_crud.get_patient_by_code(db, data.patient_code)
    if existing:
        raise HTTPException(status_code=409, detail="Patient code already exists")
    return await patient_crud.create_patient(db, data)


@router.get("/{patient_id}", response_model=PatientProfileResponse)
async def get_patient(patient_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    patient = await patient_crud.get_patient(db, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@router.get("/", response_model=list[PatientProfileResponse])
async def list_patients(skip: int = 0, limit: int = 50, db: AsyncSession = Depends(get_db)):
    return await patient_crud.list_patients(db, skip, limit)


@router.patch("/{patient_id}", response_model=PatientProfileResponse)
async def update_patient(
    patient_id: uuid.UUID, data: PatientProfileUpdate, db: AsyncSession = Depends(get_db)
):
    patient = await patient_crud.get_patient(db, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return await patient_crud.update_patient(db, patient, data)
```

- [ ] **Step 4: app/routers/drugs.py 작성**

```python
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.drug import DrugKnowledgeBaseCreate, DrugKnowledgeBaseUpdate, DrugKnowledgeBaseResponse
from app.crud import drug as drug_crud

router = APIRouter(prefix="/drugs", tags=["drugs"])


@router.post("/", response_model=DrugKnowledgeBaseResponse, status_code=status.HTTP_201_CREATED)
async def create_drug(data: DrugKnowledgeBaseCreate, db: AsyncSession = Depends(get_db)):
    return await drug_crud.create_drug(db, data)


@router.get("/search", response_model=list[DrugKnowledgeBaseResponse])
async def search_drugs(q: str = Query(..., min_length=1), db: AsyncSession = Depends(get_db)):
    return await drug_crud.search_drugs(db, q)


@router.get("/{drug_id}", response_model=DrugKnowledgeBaseResponse)
async def get_drug(drug_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    drug = await drug_crud.get_drug(db, drug_id)
    if not drug:
        raise HTTPException(status_code=404, detail="Drug not found")
    return drug


@router.get("/", response_model=list[DrugKnowledgeBaseResponse])
async def list_drugs(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    return await drug_crud.list_drugs(db, skip, limit)


@router.patch("/{drug_id}", response_model=DrugKnowledgeBaseResponse)
async def update_drug(
    drug_id: uuid.UUID, data: DrugKnowledgeBaseUpdate, db: AsyncSession = Depends(get_db)
):
    drug = await drug_crud.get_drug(db, drug_id)
    if not drug:
        raise HTTPException(status_code=404, detail="Drug not found")
    return await drug_crud.update_drug(db, drug, data)
```

- [ ] **Step 5: app/routers/prescriptions.py 작성**

```python
import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.prescription import PrescriptionLogCreate, PrescriptionLogResponse
from app.crud import prescription as prescription_crud

router = APIRouter(prefix="/prescriptions", tags=["prescriptions"])


@router.post("/", response_model=PrescriptionLogResponse, status_code=status.HTTP_201_CREATED)
async def create_prescription_log(
    data: PrescriptionLogCreate, db: AsyncSession = Depends(get_db)
):
    return await prescription_crud.create_prescription_log(db, data)


@router.get("/patient/{patient_id}", response_model=list[PrescriptionLogResponse])
async def get_patient_prescriptions(
    patient_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    return await prescription_crud.get_logs_by_patient(db, patient_id)


@router.get("/session/{session_id}", response_model=list[PrescriptionLogResponse])
async def get_session_prescriptions(
    session_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    return await prescription_crud.get_logs_by_session(db, session_id)
```

- [ ] **Step 6: app/main.py — 라우터 등록**

```python
from fastapi import FastAPI
from app.routers import patients, drugs, prescriptions

app = FastAPI(
    title="처방 가이드 시스템",
    description="성분명(Generic) 기반 범용 처방 레퍼런스 API — 실제 처방은 의사가 EMR에 직접 입력",
    version="0.1.0",
)

app.include_router(patients.router)
app.include_router(drugs.router)
app.include_router(prescriptions.router)

@app.get("/")
async def health_check():
    return {"status": "ok", "service": "prescription-guide"}
```

- [ ] **Step 7: 테스트 재실행 — 통과 확인**

```bash
pytest tests/test_routers/ -v
```

Expected: ALL PASS

- [ ] **Step 8: 커밋**

```bash
git add app/routers/ app/main.py tests/test_routers/
git commit -m "feat: FastAPI routers for patients, drugs, prescriptions"
```

---

### Task 8: Alembic 마이그레이션 설정

**Files:**
- Create: `alembic.ini`
- Create: `migrations/env.py`

- [ ] **Step 1: Alembic 초기화**

```bash
alembic init migrations
```

- [ ] **Step 2: migrations/env.py 수정 — async 엔진 + 모델 자동 감지**

```python
import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
from app.config import settings
from app.database import Base
import app.models  # 모든 모델 임포트 (테이블 자동 감지)

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: 첫 마이그레이션 생성**

```bash
alembic revision --autogenerate -m "initial_schema"
```

Expected: `migrations/versions/xxxx_initial_schema.py` 생성 확인

- [ ] **Step 4: 마이그레이션 적용**

```bash
alembic upgrade head
```

Expected: 3개 테이블 (patient_profiles, drug_knowledge_base, prescription_logs) 생성

- [ ] **Step 5: 커밋**

```bash
git add alembic.ini migrations/
git commit -m "feat: Alembic async migration setup and initial schema"
```

---

### Task 9: 로컬 서버 구동 확인

**Files:**
- Create: `.env` (`.env.example` 복사 후 실제 값 입력)

- [ ] **Step 1: .env 파일 설정**

```bash
cp .env.example .env
# DATABASE_URL 실제 PostgreSQL 연결 문자열로 수정
```

- [ ] **Step 2: 서버 구동**

```bash
uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 3: Swagger UI 접속 확인**

브라우저에서 `http://localhost:8000/docs` 접속.
다음 3개 태그 확인: `patients`, `drugs`, `prescriptions`

- [ ] **Step 4: 헬스체크**

```bash
curl http://localhost:8000/
```

Expected:
```json
{"status": "ok", "service": "prescription-guide"}
```

- [ ] **Step 5: 전체 테스트 최종 실행**

```bash
pytest tests/ -v --tb=short
```

Expected: ALL PASS

- [ ] **Step 6: 최종 커밋**

```bash
git add .
git commit -m "chore: final integration verified — prescription guide system v0.1.0"
```

---

## 스키마 요약 (ERD 개요)

```
patient_profiles
├── id (UUID PK)
├── patient_code (UNIQUE)
├── age, gender, weight_kg, height_cm
├── diseases (JSONB) ← DiseaseFlags: 15대 질환 boolean
├── lab_values (JSONB) ← LabValues: 검사 수치 22개 항목
├── allergies (TEXT[])
└── current_medications (JSONB)

drug_knowledge_base
├── id (UUID PK)
├── generic_name_ko / generic_name_en  ← 성분명만. 상품명 없음.
├── drug_class
├── indications (TEXT[])
├── contraindications (JSONB) ← {absolute:[], relative:[]}
├── standard_dosage (JSONB) ← {initial, maintenance, max_daily_mg}
├── strengths_available_mg (JSONB) ← 가용 함량 숫자 배열
├── guideline_source / guideline_year  ← 근거 문헌
└── special_populations (JSONB) ← 신/간기능, 노인, 임부 조정

prescription_logs
├── id (UUID PK)
├── patient_id (FK → patient_profiles)
├── session_id (UUID) ← 동일 진료 세션 그룹
├── drug_id (FK → drug_knowledge_base)
├── recommended_generic_name_ko / _en  ← 성분명 스냅샷
├── recommended_strength_mg
├── recommended_dose_description / frequency / duration_days
├── clinical_rationale  ← AI/가이드라인 근거
├── guideline_reference
└── warnings (TEXT[])
```
