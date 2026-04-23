import json
import re
from sqlalchemy.ext.asyncio import AsyncSession
from app.crud.feedback import get_patient_feedbacks
from app.crud.lab_history import get_recent_lab_history
from app.crud.prescription import get_logs_by_patient
from app.crud.patient import get_patient
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
