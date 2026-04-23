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
