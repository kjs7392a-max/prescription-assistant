# 처방 가이드 시스템

성분명(Generic) 기반 범용 처방 레퍼런스 API

## 시작하기

### 1. 환경 변수 설정
```bash
cp .env.example .env
# .env 파일에서 DATABASE_URL을 실제 PostgreSQL 연결 문자열로 수정
```

### 2. 데이터베이스 마이그레이션

```bash
alembic upgrade head
```

### 3. 서버 실행

```bash
uvicorn app.main:app --reload --port 8000
```

### 4. API 문서
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Railway 배포

1. railway.com → New Project → **Deploy from GitHub repo** → `kjs7392a-max/prescription-assistant`
2. 같은 프로젝트에 `+ New` → **Database** → **Add PostgreSQL** (자동으로 `DATABASE_URL` 환경변수 주입)
3. 서비스 설정 → **Variables**에 추가:
   - `ANTHROPIC_API_KEY` = `sk-ant-...`
   - `APP_ENV` = `production`
4. **Settings → Networking → Generate Domain** → 공개 URL 발급
5. `Procfile`에 따라 `alembic upgrade head` 후 uvicorn 자동 실행

## 테이블 구조

- `patient_profiles` — 환자 프로파일 (15대 질환 플래그, Lab 수치)
- `drug_knowledge_base` — 약물 지식 DB (성분명 기반, 상품명 없음)
- `prescription_logs` — 처방 가이드 이력

## API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| POST | /patients/ | 환자 등록 |
| GET | /patients/{id} | 환자 조회 |
| PATCH | /patients/{id} | 환자 정보 수정 |
| POST | /drugs/ | 약물 등록 |
| GET | /drugs/search?q= | 성분명/분류 검색 |
| GET | /drugs/{id} | 약물 조회 |
| POST | /prescriptions/ | 처방 가이드 로그 생성 |
| GET | /prescriptions/patient/{id} | 환자별 처방 이력 |
| GET | /prescriptions/session/{id} | 세션별 처방 조회 |

---

## History-Based Re-ranking Engine

`app/services/history_engine.py` — 환자의 과거 처방 이력을 현재 추천에 반영하는 결정론적 4단계 파이프라인.

```
parse_prescription_history()
  → match_history_to_current_visit()
  → evaluate_history_drug_safety()
  → enforce_history_priority()
```

### Drug Normalizer (`app/services/drug_normalizer.py`)

- `DRUG_MASTER_DB`: 70+ 약물 엔트리 (ATC code, drug_class, 상품명, aliases)
- `_NAME_INDEX` 빌드 규칙: **복합제(combination=True)의 `ingredient_names`는 인덱스 제외** — 단일 성분 엔트리 덮어쓰기 방지
- `search_by_name()` partial match: 단일 성분 우선 → ingredient_code 존재 우선 → 길이 차이 오름차순 정렬
- `normalize_drug_name(raw)`: raw_name에서 용량 자동 추출 → `NormalizedDrug.strength` 필드로 분리

### 성분 중복 탐지 (`is_duplicate_ingredient`)

단일제 ↔ 복합제 교차 탐지를 포함한 성분 중복 여부 판별.

```python
from app.services.history_engine import is_duplicate_ingredient
from app.services.drug_normalizer import normalize_drug_name

metformin = normalize_drug_name("메트포르민")
janumet   = normalize_drug_name("자누메트")   # metformin+sitagliptin
is_duplicate_ingredient(metformin, janumet)   # → True
```

**판별 우선순위:**
1. ATC ingredient_code 일치
2. 영문 ingredient_names 교집합
3. 전체 ingredient_names 교집합 (DB 미등재 성분 fallback)

3제 복합제(예: 암로디핀+로사르탄+클로르탈리돈) vs 단일제/2제 복합제 간 1개 성분이라도 겹치면 `True` 반환.

### 안전성 검사 (`evaluate_history_drug_safety`)

| 단계 | 내용 |
|---|---|
| ① | 과거 부작용 기록 (`adverse_event=True`) |
| ② | Feedback DB 부작용 이력 |
| ③ | 알레르기 — `ingredient_names` 전체 순회 |
| ④ | Lab 금기 — 복합제 성분별 개별 체크 (`_iter_drug_and_components`) |
| ⑤-a | 현재 처방약과 **성분 중복** (`is_duplicate_ingredient`) — `contraindicated` |
| ⑤-b | DDI (drug_class 쌍 기반) |
| ⑥ | 고령(≥65세) Beers 2023 경고 |

### 테스트

```bash
pytest tests/test_services/test_history_engine.py -v
```

| TC | 내용 |
|---|---|
| TC-01 | 동일 진단 과거 처방 → primary[0] 강제 배치 |
| TC-02 | 부작용 이력 → eligible=False |
| TC-03 | eGFR 25 + 메트포르민 → contraindicated |
| TC-04 | 글루코파지 → 메트포르민 정규화 (ingredient_code A10BA02) |
| TC-05 | 증상 기반 부분 매칭 → same_symptom/partial |
| TC-06 | 3제 복합제 vs 단일제/2제/DB미등재 성분 중복 탐지 |
