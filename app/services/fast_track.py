"""Fast-Track 1단계 엔진 — LLM 없이 정규식/사전 기반으로 방어 약물·용량 조절을 <0.3초 내 계산."""
import re
from app.schemas.inference import RecommendedGeneric


_NSAID_KEYS = [
    r"셀레콕시브", r"나프록센", r"이부프로펜", r"디클로페낙", r"멜록시캄",
    r"아세클로페낙", r"케토프로펜", r"피록시캄",
    r"celecoxib", r"naproxen", r"ibuprofen", r"diclofenac", r"meloxicam",
    r"aceclofenac", r"ketoprofen", r"piroxicam",
    r"NSAID", r"소염진통제",
]
_STEROID_KEYS = [
    r"프레드니솔론", r"메틸프레드니솔론", r"덱사메타손", r"하이드로코르티손",
    r"prednisolone", r"methylprednisolone", r"dexamethasone", r"hydrocortisone",
    r"스테로이드", r"steroid",
]
_MTX_KEYS = [r"메토트렉세이트", r"methotrexate", r"MTX"]
_METFORMIN_KEYS = [r"메트포르민", r"metformin"]

# 정신과 키워드 → Step 5 트리거
_PSY_KEYS = {
    "depression": [r"우울", r"우울감", r"depress"],
    "psychosis":  [r"망상", r"환청", r"환각", r"delusion", r"hallucinat", r"psychosis"],
    "agitation":  [r"공격성", r"공격적", r"초조", r"agitat", r"aggress"],
    "insomnia":   [r"불면", r"insomn"],
    "anxiety":    [r"불안", r"anxiety", r"공황"],
}
# β차단제(GDMT) — 정신과 약과 충돌 경고용
_BB_KEYS = [r"베타차단제", r"β차단제", r"비소프롤롤", r"카베디롤", r"메토프롤롤",
            r"bisoprolol", r"carvedilol", r"metoprolol", r"propranolol"]

# 고위험 약물 — Risperidone (QTc 연장·기립성 저혈압)
_RISPERIDONE_KEYS = [r"리스페리돈", r"risperidone", r"risperdal"]


def _has_any(text: str, keys: list[str]) -> bool:
    pattern = "|".join(keys)
    return bool(re.search(pattern, text, re.IGNORECASE))


def quick_safety_set(
    physician_note: str,
    diseases: dict | None,
    lab_values: dict | None,
    patient_age: int | None = None,
) -> dict:
    """정규식·사전 기반 즉시 응답.

    반환:
      {
        "defense_drugs": [RecommendedGeneric ... ],   # 방어 약물 세트
        "dose_adjustments": [str, ...],               # 용량 조절 안내 텍스트
        "contraindicated": [str, ...],                # 금기 성분
        "lab_flags": [str, ...],                      # Lab 기반 즉시 경고
      }
    """
    note = physician_note or ""
    diseases = diseases or {}
    lab = lab_values or {}
    active = {k for k, v in diseases.items() if v is True}

    defense: list[RecommendedGeneric] = []
    adjustments: list[str] = []
    contraindicated: list[str] = []
    lab_flags: list[str] = []

    egfr = lab.get("egfr")
    k_val = lab.get("potassium")
    age = patient_age

    # A. MTX → 엽산
    if _has_any(note, _MTX_KEYS):
        defense.append(RecommendedGeneric(
            generic_name_ko="엽산",
            generic_name_en="Folic Acid",
            strength_mg=5.0,
            frequency="QW",
            rationale="MTX 동반 — 조혈독성·구내염 예방 (ACR 2021)",
            guideline_reference="ACR 2021 RA — MTX + Folic Acid 표준 세트",
            risk_level="low",
            warnings=["MTX 복용일과 다른 요일에 복용"],
            drug_category="엽산 보충",
            intake_instruction="주 1회 복용 (MTX 복용 다음날)",
        ))

    # B. NSAIDs/스테로이드 → PPI
    if _has_any(note, _NSAID_KEYS) or _has_any(note, _STEROID_KEYS):
        defense.append(RecommendedGeneric(
            generic_name_ko="에소메프라졸",
            generic_name_en="Esomeprazole",
            strength_mg=20.0,
            frequency="QD",
            rationale="NSAIDs/스테로이드 동반 — 위궤양·출혈 예방 (ACG 2022)",
            guideline_reference="ACG 2022 — NSAID 유발 소화성궤양 예방",
            risk_level="low",
            warnings=["장기 복용 시 저마그네슘·골다공증 모니터"],
            drug_category="위장보호제",
            intake_instruction="식전 30분 공복 복용",
        ))

    # C. RA + DM → Celecoxib 우선
    has_ra = "rheumatoid_arthritis" in active or "류마티스" in note
    has_dm = "diabetes_type2" in active or "diabetes_type1" in active or "당뇨" in note
    if has_ra and has_dm and _has_any(note, _NSAID_KEYS):
        adjustments.append(
            "RA+T2DM: COX-2 선택억제제(Celecoxib 100~200mg BID) 우선 — "
            "신독성·심혈관 사건 감소, 혈당 영향 중립적 (ACR 2021/ADA 2026)"
        )

    # D. Metformin + eGFR 금기 체크
    if _has_any(note, _METFORMIN_KEYS):
        if egfr is not None:
            if egfr < 30:
                contraindicated.append("Metformin")
                adjustments.append(
                    f"🚫 Metformin 절대 금기 — eGFR {egfr} < 30 (KDIGO 2024) → "
                    "대체: Linagliptin 5mg QD"
                )
            elif egfr < 45:
                adjustments.append(
                    f"⚙ Metformin 감량 — eGFR {egfr} (30~44): 최대 1000mg/day, "
                    "3~6개월 재평가"
                )
            else:
                adjustments.append(f"✅ Metformin 정상 용량 가능 (eGFR {egfr})")
        else:
            adjustments.append("⚠ Metformin 처방 전 eGFR 확인 필수 (KDIGO 2024)")

    # Lab 즉시 플래그
    if egfr is not None and egfr < 30:
        lab_flags.append(f"eGFR {egfr} < 30 → NSAIDs·SGLT2i·Metformin 금기")
    if k_val is not None and k_val > 5.0:
        lab_flags.append(f"K⁺ {k_val} > 5.0 → ACEi/ARB/MRA 병용 시 모니터")
    if age is not None and age >= 65 and _has_any(note, _NSAID_KEYS):
        adjustments.append(
            f"고령({age}세) + NSAIDs: Beers 2023 PIM — "
            "국소제 또는 아세트아미노펜 대체 고려"
        )

    # ── 정신과 키워드 즉시 감지 ──
    psy_detected: list[str] = []
    psy_warnings: list[str] = []
    for tag, keys in _PSY_KEYS.items():
        if _has_any(note, keys):
            psy_detected.append(tag)
    if psy_detected:
        # GDMT(β차단제) 동반 시 충돌 경고 — 최우선 배치
        gdmt_bb = (
            "heart_failure" in active
            or "atrial_fibrillation" in active
            or "hypertension" in active
            or _has_any(note, _BB_KEYS)
        )
        if gdmt_bb:
            psy_warnings.append(
                "⚠ β차단제 + 정신과약(SSRI/항정신병약) — 기립성 저혈압·서맥·QT 연장 위험"
            )
        # 항정신병약 + QT 연장 위험
        qtc = lab.get("qtc")
        if "psychosis" in psy_detected or "agitation" in psy_detected:
            psy_warnings.append(
                "⚠ 항정신병약(Risperidone/Olanzapine 등) — QTc 모니터 필수"
                + (f" (현재 QTc {qtc}ms)" if qtc else "")
            )
        if "depression" in psy_detected:
            psy_warnings.append(
                "🟢 우울 의심 — Sertraline 50mg QD 또는 Escitalopram 10mg QD 1차 (KMAP 2024)"
            )
        if "insomnia" in psy_detected and age and age >= 65:
            psy_warnings.append(
                "⚠ 고령 + 불면 — BZD 회피(Beers 2023), Trazodone 25~50mg HS 우선"
            )

    # ── eGFR 기반 Step 용량 즉시 계산 (LLM 호출 없이 0.3초 내) ──
    egfr_steps: list[str] = []
    if egfr is not None:
        if "diabetes_type2" in active or _has_any(note, [r"당뇨"]):
            if egfr >= 45:
                egfr_steps.append(f"💊 Metformin 500~1000mg BID (eGFR {egfr})")
            elif egfr >= 30:
                egfr_steps.append(f"💊 Metformin 최대 1000mg/d 감량 (eGFR {egfr})")
            else:
                egfr_steps.append(f"💊 Linagliptin 5mg QD — Metformin 금기 (eGFR {egfr})")
        if "heart_failure" in active or "ckd" in active:
            if egfr >= 20:
                egfr_steps.append(f"💊 Empagliflozin 10mg QD 가능 (eGFR {egfr})")
            else:
                egfr_steps.append(f"🚫 SGLT2i 금기 (eGFR {egfr} < 20)")

    # ── Risperidone 즉시 감지 (QTc 연장·기립성 저혈압 고위험) ──
    risperidone_alert = None
    if _has_any(note, _RISPERIDONE_KEYS):
        has_hf = "heart_failure" in active or _has_any(note, [r"심부전", r"heart failure"])
        risperidone_alert = {
            "drug": "Risperidone",
            "headline": (
                "리스페리돈은 QTc 연장 및 기립성 저혈압 위험이 있어 "
                + ("심부전 환자에게 신중 투여가 필요합니다."
                   if has_hf
                   else "고령·심혈관 동반 환자에게 신중 투여가 필요합니다.")
            ),
            "context_hf": has_hf,
            "alternatives": [
                {"name": "Aripiprazole", "name_ko": "아리피프라졸",
                 "dose": "5~10mg QD", "reason": "부분 D2 작용제 — QT/대사 부담 최저"},
                {"name": "Quetiapine", "name_ko": "쿠에티아핀",
                 "dose": "25~50mg HS", "reason": "낮은 EPS — 진정·수면 동반 시 적합"},
            ],
            "monitoring": [
                "처방 전후 심전도(ECG) 검사 시행",
                "기립성 저혈압 발생 여부 밀착 모니터링",
            ],
        }

    return {
        "defense_drugs": [d.model_dump() for d in defense],
        "dose_adjustments": adjustments,
        "contraindicated": contraindicated,
        "lab_flags": lab_flags,
        "psychiatric_detected": psy_detected,
        "psychiatric_warnings": psy_warnings,
        "egfr_steps": egfr_steps,
        "risperidone_alert": risperidone_alert,
    }
