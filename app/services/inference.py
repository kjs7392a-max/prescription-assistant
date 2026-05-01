import json
import re
from typing import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession
from app.crud.feedback import get_patient_feedbacks
from app.crud.lab_history import get_recent_lab_history
from app.crud.prescription import get_logs_by_patient
from app.crud.patient import get_patient
from app.schemas.inference import (
    InferenceRequest,
    InferenceResponse,
    RecommendedGeneric,
    SafetyWarning,
    PrescriptionSummary,
    CompactDetails,
    GDMTStep,
    ClinicalEvidence,
    ClinicalEvidenceRef,
    PsychiatricRec,
    RxItem,
    RecommendationSet,
)
from app.schemas.history import HistoryPriorityInfo
from app.services.delta import format_delta_for_prompt
from app.services.llm.base import BaseLLMProvider
from app.services.history_engine import (
    parse_prescription_history,
    match_history_to_current_visit,
    evaluate_history_drug_safety,
    enforce_history_priority,
)

_SYSTEM_PROMPT = """\
당신은 처방 가이드 AI다. 의사가 3초 안에 스캔 가능한 한국어 JSON만 출력한다.

## 진료 컨텍스트 (중요)
- 본 시스템은 **정신과의원**에서 사용된다. 본원 의사 = 정신과 전문의.
- 정신과적 진단·처방이 주 진료다. 우울·망상·환청·공격성·불면·불안은 본원에서 직접 처방한다.
- "정신과 협진 필수" 같은 외부 의뢰 문구는 절대 출력하지 마라.
- 심혈관·대사·신장 동반질환은 정신과약과의 **병용 안전성·DDI** 관점에서만 다룬다.

## 절대 규칙
- JSON만 출력. 설명문·마크다운·인사말·서론·코드블록 금지.
- 출력은 반드시 "core" → "recommendation_set" 순서로 시작 (스트리밍 첫 1초 내 1차 처방 노출).
- 모든 1줄 필드는 60자 이내. 성분명만(상품명 금지).

## 필드별 규칙
- core: 1줄 핵심 요약 (용량 조절 / 금기 / 핵심 권고).

- recommendation_set.primary: **[주치료제 + 방어제(PPI 등) + 정신과 약물]**을 하나의 1차 추천 세트로 묶어라.
  · 각 항목 RxItem 필드: generic_name_ko, strength("10mg"), frequency("QD/BID"), form_description, category, note.
  · category: "주치료" | "방어제" | "정신과" 중 하나.
  · form_description: 복약 안내문 느낌 — "흰색 원형 정제", "노란색 서방정", "투명 캡슐", "분홍 필름코팅정" 등 (60자 이내 1줄).
  · note: 1줄 사유.
- recommendation_set.secondary: 2차 대체 세트(부작용 발생 시·금기 시).

- gdmt_steps: **진단명** 기반 치료 단계 가이드라인. Step 1~4 (max 4). Step 5(정신과)는 아래 psychiatric 규칙에서만 결정.
  · 반드시 진단명에 명시된 질환의 가이드라인으로만 구성하라. 증상 키워드만으로 단계를 추가하지 마라.
  · 리스페리돈 등 특정 약물 → QTc 연장·기립성 저혈압 위험 단계 모니터 포함.
  · 기저질환 일반 GDMT(심부전 ACC/AHA, 당뇨 ADA 등)는 gdmt_steps에 포함 금지 — details.guidelines에만 기재.
  · 각 step에 "clinical_evidence" 포함: {"rationale":"해당 단계 선택 근거 1줄","refs":[{"label":"TRIAL명 — 학회지 YYYY","pmid":"숫자"}]}. refs는 최대 2개.

- psychiatric: **진단명**에 정신과 질환(우울증·조현병·양극성장애·불안장애·불면증 등)이 명시된 경우에만 detected=true.
  · 증상란에만 우울·불안·불면 등이 언급된 경우(예: "통증으로 인한 불면")는 detected=false.
  · 감지 시: drug=적합한 정신과 약제(Aripiprazole/Quetiapine/Sertraline 등),
    consult=**용량 적정화·재평가 시점·모니터 항목** 안내.
  · 미감지 시: detected=false, drug="", consult="".

- warnings: 최대 3개, 각 1줄.
  · psychiatric.detected=true 시 **반드시** "정신과 약물 병용 시 QT 간격 연장 및 저혈압 위험 모니터링" 또는 동등 의미 문구 1개 포함.

- guidelines: 이번 메모의 증상·진단·처방에 직접 관련된 가이드라인만. 학회명·연도 (예: "KMAP 2024", "CINP 2017 조현병", "NICE 2022 우울"). 최대 5개. 기저질환 일반 가이드라인(ACC/AHA HF 등)은 제외.

- details: 긴 설명·RCT·PMID + 기저질환 GDMT 배경 정보(심부전 단계별 약물, 당뇨 단계 등)는 모두 여기에.

## 출력 JSON 스키마 (이 순서 그대로)
{
  "core":"1줄 핵심 요약",
  "recommendation_set":{
    "primary":[
      {"generic_name_ko":"성분명","strength":"10mg","frequency":"QD","form_description":"흰색 원형 정제","category":"주치료","note":"1줄 사유"}
    ],
    "secondary":[]
  },
  "gdmt_steps":[
    {"step":1,"drug":"성분명 용량 복용법","note":"선택 이유","clinical_evidence":{"rationale":"근거 1줄","refs":[{"label":"TRIAL — Journal YYYY","pmid":"12345678"}]}}
  ],
  "psychiatric":{"detected":true|false,"drug":"권고 약제","consult":"용량/모니터/재평가"},
  "warnings":["DDI/부작용 1줄"],
  "guidelines":["ACC/AHA 2023 HF","KMAP 2024"],
  "details":{
    "guidelines":"학회·단계 상세",
    "rct":"TRIAL — 저널 YYYY · PMID",
    "notes":"Lab·주의·추가 설명"
  },
  "overall_risk":"low|moderate|high|critical"
}"""


class InferenceEngine:
    def __init__(self, llm: BaseLLMProvider) -> None:
        self._llm = llm
        self._last_physician_note: str = ""

    async def analyze(
        self, db: AsyncSession, request: InferenceRequest
    ) -> InferenceResponse:
        self._last_physician_note = request.physician_note
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

        # EMR 처방이력 (접수 시 입력)
        if patient:
            meds = patient.current_medications or {}
            history_text = meds.get("history", "").strip() if isinstance(meds, dict) else ""
            if history_text:
                lines.append("## 이전 방문 처방 이력 (EMR)")
                lines.append(history_text)
                lines.append("")

        lines.append("## 의사 메모 (이번 진료)")
        lines.append(request.physician_note)
        lines.append("")

        lines.append("위 정보를 바탕으로 표준 JSON만 출력하라.")

        return "\n".join(lines)

    def _build_gdmt_context(self, patient) -> str:
        """환자 프로파일 기반 적용 가능 GDMT 컨텍스트 생성"""
        if not patient:
            return ""
        import json as _json
        diseases = {k for k, v in (patient.diseases or {}).items() if v is True}
        lab = patient.lab_values or {}
        egfr = lab.get("egfr")
        k_val = lab.get("potassium")
        notes: dict = {}
        try:
            if patient.clinical_notes:
                notes = _json.loads(patient.clinical_notes)
        except Exception:
            pass

        lines: list[str] = ["## 적용 가능 GDMT 가이드라인 컨텍스트"]

        if "heart_failure" in diseases:
            components = []
            if "acei" not in str(diseases) and "arb" not in str(diseases):
                components.append("ACEi/ARB/ARNI (1단계)")
            if "beta_blocker" not in str(diseases):
                components.append("β차단제 (1단계)")
            components.append("MRA (2단계) — K⁺ 모니터 필수")
            components.append("SGLT2i (3단계) — eGFR ≥20 시")
            lines.append(f"• 심부전 GDMT [ACC/AHA 2023]: {', '.join(components)}")

        if "diabetes_type2" in diseases or "diabetes_type1" in diseases:
            if "ckd" in diseases:
                if egfr is not None and egfr < 30:
                    lines.append("• T2DM+CKD (eGFR<30) [ADA 2026/KDIGO 2024]: "
                                 "Metformin·SGLT2i 금기 → Linagliptin 우선 (용량 조정 불필요)")
                elif egfr is None or egfr >= 20:
                    lines.append("• T2DM+CKD [ADA 2026/KDIGO 2024 EMPA-KIDNEY]: "
                                 "SGLT2i 1순위 (신기능 보호 + 심혈관 보호), eGFR ≥20 시 사용 가능")
            elif "heart_failure" in diseases:
                lines.append("• T2DM+HF [ADA 2026 DAPA-HF]: SGLT2i 우선 (입원·사망 감소)")
            elif any(d in diseases for d in ["coronary_artery_disease", "stroke", "atrial_fibrillation"]):
                lines.append("• T2DM+CVD [ADA 2026 LEADER/EMPA-REG]: SGLT2i 또는 GLP-1RA — MACE 감소")
            else:
                lines.append("• T2DM [ADA 2026]: Metformin 1단계 → SGLT2i/DPP-4 2단계; HbA1c 목표 <7.0%")

        if "ckd" in diseases:
            if egfr is not None and egfr < 15:
                lines.append("• CKD G5 [KDIGO 2024]: 대부분 약물 금기/용량 최소화, 투석 여부 확인")
            elif egfr is not None and egfr < 30:
                lines.append(f"• CKD G4 (eGFR {egfr}) [KDIGO 2024]: Metformin·NSAID·SGLT2i 금기, "
                             "NOAC 용량 주의, DPP-4(Linagliptin) 권장")
            elif egfr is not None and egfr < 60:
                lines.append(f"• CKD G3 (eGFR {egfr}) [KDIGO 2024]: RAAS 차단 + SGLT2i (eGFR≥20) 병행 권고")

        if "atrial_fibrillation" in diseases:
            lines.append("• 심방세동 [ACC/AHA/ESC 2023]: NOAC 우선 항응고 (와파린 대비 안전성 우수); "
                         "맥박수/율동 조절 전략 검토")

        if "hypertension" in diseases:
            if "diabetes_type2" in diseases or "ckd" in diseases:
                lines.append("• 고혈압+DM/CKD [ACC/AHA 2023]: ACEi 또는 ARB 1차 권고 — 신장·심혈관 보호")
            else:
                lines.append("• 고혈압 [ACC/AHA 2023]: ACEi/ARB, CCB, 티아지드 1차; 목표 <130/80 mmHg")

        if "hyperlipidemia" in diseases or "coronary_artery_disease" in diseases:
            lines.append("• 이상지질혈증/CAD [ACC/AHA 2019]: 중등도-고강도 Statin 1차; "
                         "LDL 목표 <70 mg/dL (초고위험군 <55)")

        if "copd" in diseases or "asthma" in diseases:
            lines.append("• COPD/천식 [GOLD 2024/GINA 2025]: 비선택적 β차단제 금기; "
                         "COPD→LABA/LAMA 이중, 천식→ICS 기반 단계 요법")

        ra_keys = {"rheumatoid_arthritis", "rheumatism", "ra"}
        has_ra = bool(ra_keys & diseases) or "류마티스" in str(diseases)
        has_dm = "diabetes_type2" in diseases or "diabetes_type1" in diseases
        if has_ra and has_dm:
            lines.append("• RA+T2DM 시너지 [ACR 2021/ADA 2026]: "
                         "COX-2 선택억제제(Celecoxib 100~200mg BID) 우선 — "
                         "비선택 NSAID 대비 신독성·심혈관 사건 감소, 혈당 영향 중립적")
        elif has_ra:
            lines.append("• RA [ACR 2021/EULAR 2023]: Methotrexate 1차 DMARD + "
                         "엽산(5mg QW) 동반 필수 — 조혈독성·구내염 예방")

        if "gout" in diseases:
            lines.append("• 통풍 [ACR 2020]: ULT(Allopurinol) 우선, 목표 요산 <6 mg/dL; "
                         "티아지드·루프이뇨제·아스피린 요산 상승 주의")

        if patient.age >= 65:
            lines.append(f"• 고령({patient.age}세) [Beers 2023/AGS]: "
                         "BZD·TCA·1세대항히스타민·NSAIDs·설포닐우레아·슬라이딩스케일인슐린 회피; "
                         "낙상·인지 기능 모니터")

        if k_val and k_val > 5.0:
            lines.append(f"• 고칼륨혈증 (K⁺ {k_val}) 주의: ACEI/ARB/MRA 병용 시 칼륨 급상승 위험 — 용량 조정·모니터")

        return "\n".join(lines) if len(lines) > 1 else ""

    async def stream_analyze(
        self, db: AsyncSession, request: InferenceRequest
    ) -> AsyncIterator[str]:
        """LLM 응답을 청크 단위로 스트리밍. 마지막에 __DONE__ 전송."""
        self._last_physician_note = request.physician_note
        feedbacks   = await get_patient_feedbacks(db, request.patient_id)
        lab_history = await get_recent_lab_history(db, request.patient_id, limit=3)
        recent_logs = (await get_logs_by_patient(db, request.patient_id))[:3]
        patient     = await get_patient(db, request.patient_id)

        user_prompt = self._build_user_prompt(
            patient=patient, feedbacks=feedbacks,
            lab_history=lab_history, recent_logs=recent_logs, request=request,
        )
        async for chunk in self._llm.stream_complete(system=_SYSTEM_PROMPT, user=user_prompt):
            yield chunk
        yield "__DONE__"

    def apply_history_priority(
        self,
        response: InferenceResponse,
        patient,
        feedbacks: list,
        recent_logs: list,
        disease_updates=None,
    ) -> InferenceResponse:
        """히스토리 기반 결정론적 re-ranking을 InferenceResponse에 적용."""
        try:
            meds = patient.current_medications or {} if patient else {}
            history_text = "\n".join(filter(None, [
                meds.get("history", "").strip() if isinstance(meds, dict) else "",
                meds.get("prescription", "").strip() if isinstance(meds, dict) else "",
            ]))
            if not history_text and not recent_logs:
                return response

            history_drugs = parse_prescription_history(history_text, recent_logs)
            if not history_drugs:
                return response

            patient_diseases = list({
                k for k, v in (patient.diseases or {}).items() if v is True
            }) if patient else []
            disease_update_dict = disease_updates.model_dump() if disease_updates else {}

            matched = match_history_to_current_visit(
                history_drugs,
                self._last_physician_note,
                disease_update_dict,
                patient_diseases,
            )
            if not matched:
                return response

            lab = (patient.lab_values or {}) if patient else {}
            lab_for_safety = dict(lab)
            if patient and hasattr(patient, "age") and patient.age:
                lab_for_safety["_patient_age"] = patient.age

            allergies = (patient.allergies or []) if patient else []
            safety_results = evaluate_history_drug_safety(
                matched,
                [],
                allergies,
                lab_for_safety,
                feedbacks,
            )
            if not safety_results:
                return response

            # 모든 결과(eligible + excluded) 전달 — enforce 내부에서 분기 처리
            new_rec_set, extra_warnings, priority_info = enforce_history_priority(
                response.recommendation_set,
                response.prescription_set,
                safety_results,
            )
            response.recommendation_set = new_rec_set
            if extra_warnings:
                response.warnings = (extra_warnings + response.warnings)[:3]
            response.history_priority = priority_info
        except Exception:
            pass
        return response

    @staticmethod
    def _sanitize_json(text: str) -> str:
        """JSON 문자열 내부의 리터럴 개행·탭 등 제어문자를 이스케이프로 변환."""
        result: list[str] = []
        in_string = False
        escape_next = False
        for ch in text:
            if escape_next:
                result.append(ch)
                escape_next = False
            elif ch == "\\" and in_string:
                result.append(ch)
                escape_next = True
            elif ch == '"':
                in_string = not in_string
                result.append(ch)
            elif in_string and ch == "\n":
                result.append("\\n")
            elif in_string and ch == "\r":
                result.append("\\r")
            elif in_string and ch == "\t":
                result.append("\\t")
            else:
                result.append(ch)
        return "".join(result)

    def _parse_response(self, raw: str) -> InferenceResponse:
        data = self._recover_json(raw)
        if data is None:
            return self._fallback_response()

        def _parse_generics(lst: list) -> list[RecommendedGeneric]:
            result = []
            for g in (lst or []):
                try:
                    result.append(RecommendedGeneric(**{
                        k: v for k, v in g.items()
                        if k in RecommendedGeneric.model_fields
                    }))
                except Exception:
                    pass
            return result

        prescription_set = _parse_generics(data.get("prescription_set", []))
        recommended_generics = _parse_generics(data.get("recommended_generics", [])) or prescription_set

        contraindicated = list(data.get("contraindicated_generics", []))
        prescription_set, contraindicated = self._enforce_safety_set(
            prescription_set, contraindicated
        )
        if not _parse_generics(data.get("recommended_generics", [])):
            recommended_generics = prescription_set

        compact = self._build_compact(data, prescription_set, contraindicated)
        std = self._build_standard_template(data, prescription_set)
        rec_set = self._build_recommendation_set(data, std, prescription_set)

        return InferenceResponse(
            # 새 표준 필드
            core=std["core"],
            recommendation_set=rec_set,
            gdmt_steps=std["gdmt_steps"],
            psychiatric=std["psychiatric"],
            warnings=std["warnings"],
            guidelines=std["guidelines"],
            details=compact["details"],
            # 백워드 호환
            safetyWarnings=compact["safetyWarnings"],
            prescription=compact["prescription"],
            reasons=compact["reasons"],
            prescription_set=prescription_set,
            recommended_generics=recommended_generics,
            contraindicated_generics=contraindicated,
            lab_delta_summary=data.get("lab_delta_summary", ""),
            overall_risk=data.get("overall_risk", "moderate"),
            physician_action_required=data.get("physician_action_required", True),
            evidence_commentary=data.get("evidence_commentary", ""),
            key_rct_references=data.get("key_rct_references", []),
            deep_insight=data.get("deep_insight", ""),
        )

    @staticmethod
    def _one_line(s: str, limit: int = 80) -> str:
        """개행·중복공백 제거, 길이 제한."""
        if not s:
            return ""
        s = re.sub(r"\s+", " ", str(s)).strip()
        if len(s) > limit:
            s = s[:limit].rstrip() + "…"
        return s

    def _parse_clinical_evidence(self, raw) -> ClinicalEvidence | None:
        if not isinstance(raw, dict):
            return None
        rationale = self._one_line(raw.get("rationale", ""), 120)
        refs = []
        for r in (raw.get("refs") or [])[:2]:
            if not isinstance(r, dict):
                continue
            label = self._one_line(r.get("label", ""), 80)
            if label:
                refs.append(ClinicalEvidenceRef(
                    label=label,
                    pmid=str(r["pmid"]) if r.get("pmid") else None,
                    url=r.get("url"),
                ))
        return ClinicalEvidence(rationale=rationale, refs=refs) if (rationale or refs) else None

    def _build_compact(
        self,
        data: dict,
        prescription_set: list[RecommendedGeneric],
        contraindicated: list[str],
    ) -> dict:
        """LLM 응답(자유도 있는) → 고정 UI compact 4필드로 정규화."""
        # ── safetyWarnings (최대 3개) ──
        warnings: list[SafetyWarning] = []
        raw_sw = data.get("safetyWarnings") or []
        for w in raw_sw[:6]:
            if not isinstance(w, dict):
                continue
            lvl = w.get("level", "caution")
            if lvl not in ("contraindication", "caution", "dose"):
                lvl = "caution"
            text = self._one_line(w.get("text", ""), 80)
            if text:
                warnings.append(SafetyWarning(level=lvl, text=text))
        # 부족하면 기존 필드에서 보강
        if len(warnings) < 3:
            for name in contraindicated[: 3 - len(warnings)]:
                warnings.append(SafetyWarning(
                    level="contraindication",
                    text=self._one_line(f"{name} 금기", 80),
                ))
        if len(warnings) < 3:
            for g in prescription_set:
                if len(warnings) >= 3:
                    break
                if g.dose_adjustment:
                    warnings.append(SafetyWarning(
                        level="dose",
                        text=self._one_line(f"{g.generic_name_ko}: {g.dose_adjustment}", 80),
                    ))
        warnings = warnings[:3]

        # ── prescription.summary (1줄) ──
        raw_px = data.get("prescription") or {}
        summary = ""
        if isinstance(raw_px, dict):
            summary = self._one_line(raw_px.get("summary", ""), 100)
        if not summary and prescription_set:
            parts = []
            for g in prescription_set[:4]:
                dose = f"{int(g.strength_mg)}mg " if g.strength_mg else ""
                parts.append(f"{g.generic_name_ko} {dose}{g.frequency}".strip())
            summary = self._one_line(" / ".join(parts), 120)

        # ── reasons (최대 3개, 각 1줄) ──
        reasons: list[str] = []
        for r in (data.get("reasons") or [])[:6]:
            t = self._one_line(r, 80)
            if t:
                reasons.append(t)
        if len(reasons) < 3:
            for g in prescription_set:
                if len(reasons) >= 3:
                    break
                t = self._one_line(g.rationale, 80)
                if t and t not in reasons:
                    reasons.append(t)
        reasons = reasons[:3]

        # ── details (긴 텍스트는 여기에만) ──
        raw_d = data.get("details") or {}
        guidelines = raw_d.get("guidelines") if isinstance(raw_d, dict) else ""
        rct = raw_d.get("rct") if isinstance(raw_d, dict) else ""
        notes = raw_d.get("notes") if isinstance(raw_d, dict) else ""

        if not guidelines:
            refs = [g.guideline_reference for g in prescription_set if g.guideline_reference]
            guidelines = " · ".join(dict.fromkeys(refs))
        if not rct:
            rct = " / ".join(data.get("key_rct_references") or [])
        if not notes:
            notes_parts = []
            if data.get("deep_insight"):
                notes_parts.append(str(data["deep_insight"]))
            if data.get("evidence_commentary"):
                notes_parts.append(str(data["evidence_commentary"]))
            if data.get("lab_delta_summary"):
                notes_parts.append("Lab: " + str(data["lab_delta_summary"]))
            notes = "\n\n".join(notes_parts)

        return {
            "safetyWarnings": warnings,
            "prescription": PrescriptionSummary(summary=summary),
            "reasons": reasons,
            "details": CompactDetails(
                guidelines=str(guidelines or ""),
                rct=str(rct or ""),
                notes=str(notes or ""),
            ),
        }

    def _build_standard_template(
        self,
        data: dict,
        prescription_set: list[RecommendedGeneric],
    ) -> dict:
        """LLM 응답 → 표준 6필드(core/gdmt_steps/psychiatric/warnings/guidelines/details) 정규화."""
        # core
        core = self._one_line(data.get("core") or data.get("lab_delta_summary", ""), 90)

        # gdmt_steps (max 5 — Step 5 = 정신건강)
        steps: list[GDMTStep] = []
        for s in (data.get("gdmt_steps") or [])[:8]:
            if not isinstance(s, dict):
                continue
            try:
                step_num = int(s.get("step", len(steps) + 1))
            except (TypeError, ValueError):
                step_num = len(steps) + 1
            drug = self._one_line(s.get("drug", ""), 80)
            note = self._one_line(s.get("note", ""), 80)
            ev = self._parse_clinical_evidence(s.get("clinical_evidence"))
            if drug:
                steps.append(GDMTStep(step=step_num, drug=drug, note=note, clinical_evidence=ev))
        if not steps:
            for i, g in enumerate(prescription_set[:4], 1):
                dose = f"{int(g.strength_mg)}mg " if g.strength_mg else ""
                drug = self._one_line(
                    f"{g.generic_name_ko} {dose}{g.frequency} {g.intake_instruction or ''}".strip(),
                    80,
                )
                steps.append(GDMTStep(
                    step=i,
                    drug=drug,
                    note=self._one_line(g.rationale, 80),
                ))
        steps = steps[:5]

        # psychiatric
        psy_raw = data.get("psychiatric") or {}
        if isinstance(psy_raw, dict):
            psy = PsychiatricRec(
                detected=bool(psy_raw.get("detected", False)),
                drug=self._one_line(psy_raw.get("drug", ""), 80),
                consult=self._one_line(psy_raw.get("consult", ""), 80),
            )
        else:
            psy = PsychiatricRec()

        # Step 5 자동 보강 — psychiatric.detected=true인데 step 5 누락 시
        if psy.detected and not any(s.step == 5 for s in steps):
            step5_drug = psy.drug or "Aripiprazole 5mg QD 또는 Quetiapine 25mg HS"
            steps.append(GDMTStep(
                step=5,
                drug=self._one_line(step5_drug, 80),
                note=self._one_line(
                    "심독성 낮은 항정신병제 우선 (KMAP 2024)", 80,
                ),
            ))
            steps = steps[:5]

        # warnings (max 3) — QT/저혈압 경고 강제 주입
        warns: list[str] = []
        for w in (data.get("warnings") or [])[:6]:
            if isinstance(w, dict):
                w = w.get("text", "")
            t = self._one_line(w, 80)
            if t:
                warns.append(t)
        if psy.detected:
            qt_terms = ("qt", "QT", "기립", "저혈압", "orthostat")
            if not any(any(term in w for term in qt_terms) for w in warns):
                warns.insert(0, "정신과 약물 병용 시 QT 간격 연장 및 저혈압 위험 모니터링")
        warns = warns[:3]

        # guidelines (max 5, 학회명만)
        guides: list[str] = []
        for g in (data.get("guidelines") or [])[:8]:
            t = self._one_line(g, 60)
            if t:
                guides.append(t)
        # 부족하면 prescription_set의 guideline_reference에서 학회명만 추출
        if not guides:
            for g in prescription_set:
                if g.guideline_reference:
                    short = self._one_line(g.guideline_reference.split("—")[0].split("·")[0], 50)
                    if short and short not in guides:
                        guides.append(short)
        guides = guides[:5]

        return {
            "core": core,
            "gdmt_steps": steps,
            "psychiatric": psy,
            "warnings": warns,
            "guidelines": guides,
        }

    def _build_recommendation_set(
        self,
        data: dict,
        std: dict,
        prescription_set: list[RecommendedGeneric],
    ) -> RecommendationSet:
        """LLM의 recommendation_set을 RxItem으로 정규화. 누락 시 gdmt_steps + psychiatric로 fallback."""
        def _to_rx(d: dict) -> RxItem | None:
            if not isinstance(d, dict):
                return None
            name = self._one_line(d.get("generic_name_ko") or d.get("name") or "", 60)
            if not name:
                return None
            return RxItem(
                generic_name_ko=name,
                strength=self._one_line(d.get("strength", ""), 30),
                frequency=self._one_line(d.get("frequency", ""), 40),
                form_description=self._one_line(d.get("form_description", ""), 60),
                category=self._one_line(d.get("category", ""), 20) or "주치료",
                note=self._one_line(d.get("note", ""), 80),
            )

        raw = data.get("recommendation_set") or {}
        primary: list[RxItem] = []
        secondary: list[RxItem] = []
        if isinstance(raw, dict):
            for d in (raw.get("primary") or [])[:8]:
                rx = _to_rx(d)
                if rx:
                    primary.append(rx)
            for d in (raw.get("secondary") or [])[:6]:
                rx = _to_rx(d)
                if rx:
                    secondary.append(rx)

        # Fallback: LLM이 recommendation_set을 안 채웠을 때 gdmt_steps에서 합성
        if not primary:
            for s in std["gdmt_steps"][:4]:
                # drug 문자열에서 성분명/용량/복용법 분리 시도
                tokens = s.drug.split()
                name = tokens[0] if tokens else s.drug
                strength = next((t for t in tokens if any(c.isdigit() for c in t)), "")
                freq = next(
                    (t for t in tokens if t.upper() in ("QD", "BID", "TID", "QID", "QW", "HS", "PRN")),
                    "",
                )
                cat = "정신과" if s.step == 5 else "주치료"
                primary.append(RxItem(
                    generic_name_ko=name,
                    strength=strength,
                    frequency=freq or "QD",
                    form_description="",
                    category=cat,
                    note=s.note,
                ))
            # 정신과 권고 별도 추가 (Step 5 누락 시)
            psy = std["psychiatric"]
            if psy.detected and not any(p.category == "정신과" for p in primary):
                primary.append(RxItem(
                    generic_name_ko=(psy.drug.split()[0] if psy.drug else "Aripiprazole"),
                    strength="5mg" if not psy.drug else "",
                    frequency="QD",
                    form_description="",
                    category="정신과",
                    note=psy.consult or "심독성 낮은 항정신병제 (KMAP 2024)",
                ))

        return RecommendationSet(primary=primary[:6], secondary=secondary[:5])

    def _recover_json(self, raw: str) -> dict | None:
        """LLM 응답에서 JSON을 추출. 코드펜스·머리말·잘림·후행 텍스트에 강건."""
        if not raw:
            return None
        text = raw.strip()

        # 1) 코드펜스 제거
        text = re.sub(r"```(?:json|JSON)?\s*\n?", "", text)
        text = re.sub(r"\n?```", "", text)

        # 2) 첫 '{' 부터 슬라이스 (LLM이 머리말 붙여도 잘라냄)
        start = text.find("{")
        if start < 0:
            return None
        body = text[start:]

        # 3) 균형 잡힌 첫 객체만 추출 (문자열 내부 중괄호 무시)
        end = self._find_balanced_end(body)
        if end > 0:
            try:
                return json.loads(self._sanitize_json(body[:end]))
            except json.JSONDecodeError:
                pass

        # 4) 마지막 '}' 까지로 잘라 재시도
        last = body.rfind("}")
        if last > 0:
            try:
                return json.loads(self._sanitize_json(body[: last + 1]))
            except json.JSONDecodeError:
                pass

        # 5) 잘린 JSON 복구 — 미완 토큰 제거 + 누락 닫는 괄호 보충
        recovered = body
        recovered = re.sub(r',\s*"[^"]*$', "", recovered)
        recovered = re.sub(r',\s*[^,\[\]\{\}]*$', "", recovered)
        recovered = recovered.rstrip(",  \n\r\t")
        depth_obj = recovered.count("{") - recovered.count("}")
        depth_arr = recovered.count("[") - recovered.count("]")
        if depth_obj > 0 or depth_arr > 0:
            recovered = recovered + ("]" * max(depth_arr, 0)) + ("}" * max(depth_obj, 0))
        try:
            return json.loads(self._sanitize_json(recovered))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _find_balanced_end(text: str) -> int:
        """text[0]=='{'에서 시작해 균형 잡힌 객체 끝 인덱스(exclusive) 반환. 실패 시 -1."""
        if not text or text[0] != "{":
            return -1
        depth = 0
        in_str = False
        escape = False
        for i, ch in enumerate(text):
            if escape:
                escape = False
                continue
            if ch == "\\" and in_str:
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        return -1

    def _fallback_response(self) -> InferenceResponse:
        # 의사가 한 줄만 보고 즉시 행동 가능하도록 — 노이즈 제거.
        # 상세 jargon, 부가 설명, 멀티 라인 모두 제외.
        return InferenceResponse(
            core="AI 분석 일시 불가 — [🔄 재분석] 또는 임상판단으로 진행",
            recommendation_set=RecommendationSet(),
            gdmt_steps=[],
            psychiatric=PsychiatricRec(),
            warnings=[],
            guidelines=[],
            details=CompactDetails(),
            safetyWarnings=[],
            prescription=PrescriptionSummary(summary=""),
            reasons=[],
            prescription_set=[],
            recommended_generics=[],
            contraindicated_generics=[],
            lab_delta_summary="",
            overall_risk="moderate",
            physician_action_required=True,
            evidence_commentary="",
            key_rct_references=[],
            deep_insight="",
        )

    @staticmethod
    def _enforce_safety_set(
        drugs: list[RecommendedGeneric], contraindicated: list[str]
    ) -> tuple[list[RecommendedGeneric], list[str]]:
        """LLM이 방어 처방(Safety Set)을 누락했을 때 프로그래밍적으로 보강."""
        def _name_blob(g: RecommendedGeneric) -> str:
            return f"{g.generic_name_ko or ''} {g.generic_name_en or ''}".lower()

        NSAIDS = [
            "celecoxib", "naproxen", "ibuprofen", "diclofenac", "meloxicam",
            "aceclofenac", "etodolac", "ketoprofen", "piroxicam",
            "셀레콕시브", "나프록센", "이부프로펜", "디클로페낙", "멜록시캄",
            "아세클로페낙", "케토프로펜",
        ]
        STEROIDS = [
            "prednisolone", "methylprednisolone", "dexamethasone", "hydrocortisone",
            "triamcinolone",
            "프레드니솔론", "메틸프레드니솔론", "덱사메타손", "하이드로코르티손",
        ]
        PPI_H2RA = [
            "esomeprazole", "pantoprazole", "omeprazole", "rabeprazole",
            "lansoprazole", "famotidine", "ranitidine",
            "에소메프라졸", "판토프라졸", "오메프라졸", "라베프라졸",
            "란소프라졸", "파모티딘",
        ]

        def _has_any(keys: list[str]) -> bool:
            return any(k in _name_blob(g) for g in drugs for k in keys)

        blobs = [_name_blob(g) for g in drugs]

        # A. Methotrexate → Folic Acid
        if any("methotrexate" in b or "메토트렉세이트" in b for b in blobs):
            if not any("folic" in b or "엽산" in b for b in blobs):
                drugs.append(RecommendedGeneric(
                    generic_name_ko="엽산",
                    generic_name_en="Folic Acid",
                    strength_mg=5.0,
                    frequency="QW",
                    rationale="메토트렉세이트 동반 처방 — 조혈독성·구내염·간독성 예방 (Safety Set 자동 추가)",
                    guideline_reference="ACR 2021 RA — MTX + Folic Acid 표준 세트",
                    risk_level="low",
                    warnings=["MTX 복용일과 다른 요일에 복용"],
                    dose_adjustment=None,
                    drug_category="엽산 보충",
                    intake_instruction="주 1회 복용 (MTX 복용 다음날)",
                ))

        # B. NSAIDs/Steroid → PPI or H2RA
        has_nsaid_or_steroid = _has_any(NSAIDS) or _has_any(STEROIDS)
        has_gi_protector = _has_any(PPI_H2RA)
        if has_nsaid_or_steroid and not has_gi_protector:
            drugs.append(RecommendedGeneric(
                generic_name_ko="에소메프라졸",
                generic_name_en="Esomeprazole",
                strength_mg=20.0,
                frequency="QD",
                rationale="NSAIDs/스테로이드 동반 — 위궤양·출혈 예방 (Safety Set 자동 추가)",
                guideline_reference="ACG 2022 — NSAID 유발 소화성궤양 예방",
                risk_level="low",
                warnings=["장기 복용 시 저마그네슘·골다공증 모니터"],
                dose_adjustment=None,
                drug_category="위장보호제",
                intake_instruction="식전 30분 공복 복용",
            ))

        # 누락된 카테고리/복약지시 보정
        GUESS_CATEGORY = [
            (["metformin", "메트포르민", "linagliptin", "리나글립틴",
              "empagliflozin", "dapagliflozin", "엠파글리플로진", "다파글리플로진"], "당뇨약"),
            (NSAIDS, "관절염약(NSAIDs)"),
            (STEROIDS, "스테로이드(소염제)"),
            (PPI_H2RA, "위장보호제"),
            (["methotrexate", "메토트렉세이트"], "면역조절제(DMARD)"),
            (["folic", "엽산"], "엽산 보충"),
            (["amlodipine", "losartan", "valsartan", "lisinopril",
              "암로디핀", "로사르탄", "발사르탄"], "혈압약"),
            (["atorvastatin", "rosuvastatin", "아토르바스타틴", "로수바스타틴"], "고지혈증약"),
            (["furosemide", "spironolactone", "푸로세마이드", "스피로노락톤"], "이뇨제"),
            (["warfarin", "apixaban", "rivaroxaban", "와파린", "아픽사반"], "항응고제"),
        ]
        for g in drugs:
            if not g.drug_category:
                blob = _name_blob(g)
                for keys, cat in GUESS_CATEGORY:
                    if any(k in blob for k in keys):
                        g.drug_category = cat
                        break
            if not g.intake_instruction:
                blob = _name_blob(g)
                if any(k in blob for k in NSAIDS) or any(k in blob for k in STEROIDS):
                    g.intake_instruction = "식사 직후 복용 (위 자극 최소화)"
                elif any(k in blob for k in PPI_H2RA):
                    g.intake_instruction = "식전 30분 공복 복용"
                elif "metformin" in blob or "메트포르민" in blob:
                    g.intake_instruction = "식사 직후 복용 (위장 부작용 감소)"
                elif "folic" in blob or "엽산" in blob:
                    g.intake_instruction = "주 1회 복용"

        return drugs, contraindicated
