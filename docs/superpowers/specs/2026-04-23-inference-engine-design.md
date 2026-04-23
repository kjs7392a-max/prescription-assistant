# Inference Engine & History System Design

**Goal:** 환자의 Lab 수치 시계열과 부작용 이력을 기반으로 LLM이 델타(변화량)를 인지하여 성분명 처방 가이드를 생성하는 지능형 추론 엔진 구축

---

## 결정 사항 (brainstorming 확인)

| 항목 | 결정 |
|---|---|
| 진단 메모 입력 | 혼합형 (구조화 필드 + 자유 서술) |
| LLM API | 추상화 레이어 (LLMProvider 인터페이스, 기본 Claude) |
| 부작용·수정 이력 | 별도 `prescription_feedback` 테이블 (1:N) |
| Lab 시계열 | 별도 `patient_lab_history` 테이블 |
| Inference 방식 | Service Layer (동기식) — POST → 즉시 응답 |

---

## 1. DB 스키마 확장

### `patient_lab_history`
```
id          UUID PK
patient_id  UUID FK → patient_profiles.id (indexed)
recorded_at DateTime (indexed)
lab_values  JSONB  ← LabValues 스냅샷
source      String  ← "manual" | "emr_import"
```
`PatientProfile.lab_values`는 최신값 캐시로 유지. Lab 업데이트 시 항상 여기에 INSERT + PatientProfile 갱신 (atomic).

### `prescription_feedback`
```
id                   UUID PK
prescription_log_id  UUID FK → prescription_logs.id (indexed)
patient_id           UUID FK → patient_profiles.id (indexed)
feedback_type        String  ← "adverse_event" | "physician_override" | "dose_adjusted"
severity             String  ← "mild" | "moderate" | "severe" | null
description          Text
affected_generic_ko  String
affected_generic_en  String
recorded_by          String
created_at           DateTime
```
Inference Engine에서 **최우선 컨텍스트**로 사용. 해당 성분에 부작용 기록이 있으면 AI가 회피.

---

## 2. LLM 추상화 레이어

```
app/services/llm/
├── __init__.py
├── base.py      ← BaseLLMProvider (ABC)
└── claude.py    ← ClaudeProvider (anthropic SDK, claude-sonnet-4-6)
```

`BaseLLMProvider` 인터페이스:
```python
async def complete(self, system: str, user: str) -> str: ...
```

`ClaudeProvider`는 Anthropic SDK를 사용하며 `ANTHROPIC_API_KEY` 환경변수로 인증.

---

## 3. InferenceEngine 알고리즘

`app/services/inference.py` — `InferenceEngine` 클래스

### 분석 우선순위 (Priority)

```
Priority 1: prescription_feedback 조회
  → 해당 환자의 부작용/수정 이력 전체 로드
  → feedback_type=adverse_event 성분을 "금기 목록" 확정

Priority 2: patient_lab_history 최근 3회 Delta 계산
  → 각 시점의 주요 수치(eGFR, HbA1c, LDL, K+ 등) 추출
  → delta = current - previous (양수=상승, 음수=하강)
  → 급격한 변화 감지 (|delta| > threshold → "급격한 변화" 플래그)

Priority 3: 컨텍스트 조립 → LLM 프롬프트 생성
  → 금기 성분 목록
  → Lab 시계열 + Delta 텍스트
  → 현재 질환 플래그
  → 의사 자유 서술 메모
  → 기존 PrescriptionLog 최근 3건

Priority 4: LLM 호출 → JSON 파싱 → 구조화 응답 반환
```

### 응답 구조
```json
{
  "recommended_generics": [
    {
      "generic_name_ko": "에날라프릴",
      "generic_name_en": "Enalapril",
      "strength_mg": 2.5,
      "frequency": "BID",
      "rationale": "심부전 + eGFR 55 → ACE억제제 1차 선택, 저용량 시작",
      "guideline_reference": "ESC HF 2023 §7.2",
      "risk_level": "moderate",
      "warnings": ["첫 투여 후 저혈압 모니터링"]
    }
  ],
  "contraindicated_generics": ["메트포르민"],
  "lab_delta_summary": "eGFR: 60→55→40 (↓33%, 급격한 하강)",
  "overall_risk": "high",
  "physician_action_required": true
}
```

---

## 4. API 엔드포인트

`POST /api/v1/inference/analyze`

Request body:
```json
{
  "patient_id": "uuid",
  "visit_date": "2026-04-23",
  "current_lab_values": { "egfr": 40, "hba1c": 7.2 },
  "disease_updates": { "heart_failure": true },
  "physician_note": "지난달보다 숨참 심해짐. 메트포르민 계속 쓸지 검토 필요."
}
```

Response: 위 JSON 구조 반환.

---

## 파일 맵

```
app/
├── models/
│   ├── lab_history.py       (신규)
│   └── feedback.py          (신규)
├── schemas/
│   ├── lab_history.py       (신규)
│   ├── feedback.py          (신규)
│   └── inference.py         (신규)
├── crud/
│   ├── lab_history.py       (신규)
│   └── feedback.py          (신규)
├── services/
│   ├── llm/
│   │   ├── __init__.py      (신규)
│   │   ├── base.py          (신규)
│   │   └── claude.py        (신규)
│   └── inference.py         (신규)
└── routers/
    └── inference.py         (신규)
```
