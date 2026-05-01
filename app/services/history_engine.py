"""처방 히스토리 기반 서버단 결정론적 Re-ranking 엔진.

흐름:
  parse_prescription_history()
    → match_history_to_current_visit()
    → evaluate_history_drug_safety()
    → enforce_history_priority()
"""
import re
from datetime import datetime
from app.schemas.history import (
    HistoryDrug,
    HistoryMatch,
    HistorySafetyResult,
    HistoryPriorityInfo,
    PromotedHistoryItem,
    ExcludedHistoryItem,
    NormalizedDrug,
)
from app.schemas.inference import RxItem, RecommendationSet, RecommendedGeneric
from app.services.drug_normalizer import normalize_drug_name, DRUG_MASTER_DB

# ──────────────────────────────────────────────────────────────────────────────
# 내부 상수
# ──────────────────────────────────────────────────────────────────────────────
_DATE_RE = re.compile(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})")
_STRENGTH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|mcg|g|정|캡슐|ml|IU)", re.IGNORECASE)
_FREQ_RE = re.compile(
    r"\b(qd|bid|tid|qid|qhs|hs|qw|prn|q\d+h|아침|저녁|취침\s*전|식후|식전|주\s*\d+회)\b",
    re.IGNORECASE,
)
_EFFECT_POSITIVE = re.compile(r"효과\s*(있|좋|good|improved|호전|잘\s*맞)", re.IGNORECASE)
_EFFECT_NEGATIVE = re.compile(r"효과\s*(없|no\s*effect|변화없|ineffect)", re.IGNORECASE)
_ADVERSE_RE = re.compile(
    r"(부작용|adverse|낙상|혈관부종|두드러기|발진|구역|구토|간독성|신독성"
    r"|저혈당|고혈당|QT|심계항진|어지럼|기립성\s*저혈압|졸림|과진정)",
    re.IGNORECASE,
)
_SECTION_DIAG_RE = re.compile(r"#\s*(.+)|진단\s*[:：]\s*(.+)|diagnosis\s*[:：]\s*(.+)", re.IGNORECASE)
_SECTION_SYM_RE = re.compile(r"증상\s*[:：]\s*(.+)|symptom\s*[:：]\s*(.+)", re.IGNORECASE)

# 약물명 후보에서 제외할 비약물 토큰 패턴
_NON_DRUG_TOKEN_RE = re.compile(
    r"^("
    # 효과 지시어
    r"효과\s*(있|없|좋|나쁨|good|bad|improved|잘\s*맞|있음|없음|좋음)"
    r"|호전|개선|무효|중단|어지러움|졸림|낙상|혈관부종|두드러기"
    # 복용법 잔여 (이미 _FREQ_RE 처리 후 남는 경우 대비)
    r"|qd|bid|tid|qid|qhs|hs|prn|q\.d|b\.i\.d|t\.i\.d|q\d+h|qw"
    r"|아침|저녁|취침\s*전|식후|식전|주\s*\d+회"
    # 용량/단위 잔여
    r"|\d+(?:\.\d+)?\s*(mg|mcg|g|정|캡슐|ml|iu|tab|cap|t)"
    r"|\d+t|\d+tab|\d+cap"
    # 기타 비약물 단어
    r"|진단|증상|처방|복용|투약|비고|메모"
    r")$",
    re.IGNORECASE,
)


def _is_non_drug_history_token(token: str) -> bool:
    """약물명으로 사용할 수 없는 토큰 여부 판단."""
    if not token or len(token) <= 1:
        return True
    return bool(_NON_DRUG_TOKEN_RE.match(token))


# 한글 성분명 → 영문 표준 성분명 매핑 (DRUG_MASTER_DB에서 자동 구축)
# 모든 DB 엔트리의 ingredient_names를 순회하여 한글명:영문명 쌍을 추출한다.
_KO_TO_EN_ING: dict[str, str] = {}
for _db_entry in DRUG_MASTER_DB.values():
    _ing = _db_entry.get("ingredient_names", [])
    _en_keys = [re.sub(r"[\s\-]", "", n.lower()) for n in _ing if re.search(r"[a-zA-Z]", n)]
    _ko_keys = [re.sub(r"[\s\-]", "", n.lower()) for n in _ing if not re.search(r"[a-zA-Z]", n)]
    if _en_keys:
        for _ko_key in _ko_keys:
            if _ko_key not in _KO_TO_EN_ING:
                _KO_TO_EN_ING[_ko_key] = _en_keys[0]


def _normalize_ing(s: str) -> str:
    """성분명 비교용 정규화: 소문자 + 공백·하이픈 제거 후 한글→영문 표준명 치환."""
    norm = re.sub(r"[\s\-]", "", s.lower())
    return _KO_TO_EN_ING.get(norm, norm)


def _iter_drug_and_components(nd: NormalizedDrug):
    """약물 자체와 복합제 성분 NormalizedDrug을 순차 yield (Lab 안전성 체크용)."""
    yield nd
    if nd.is_combination:
        for comp_key in nd.components:
            comp = normalize_drug_name(comp_key)
            if comp.ingredient_code:
                yield comp


def _find_overlapping_ingredients(drug1: NormalizedDrug, drug2: NormalizedDrug) -> list[str]:
    """두 약물 간 중복 성분의 표시명 리스트 반환.

    - ATC ingredient_code 일치 시 단일 성분명 반환
    - 이후 _normalize_ing(한글→영문 치환 포함) 기반 교집합으로 탐지
    - 반환값이 빈 리스트면 중복 없음
    """
    if drug1.ingredient_code and drug2.ingredient_code:
        if drug1.ingredient_code == drug2.ingredient_code:
            return [drug1.normalized_name]

    # {정규화키: 원본명} — 한글은 영문으로 치환되므로 교차 매칭 가능
    names1_map: dict[str, str] = {_normalize_ing(n): n for n in drug1.ingredient_names if n}
    names2_set: set[str] = {_normalize_ing(n) for n in drug2.ingredient_names if n}
    overlap_keys = set(names1_map.keys()) & names2_set

    display: list[str] = []
    for key in sorted(overlap_keys):
        raw = names1_map[key]
        nd = normalize_drug_name(raw)
        display.append(nd.normalized_name if nd.ingredient_code else raw)
    return display


def is_duplicate_ingredient(drug1: NormalizedDrug, drug2: NormalizedDrug) -> bool:
    """두 NormalizedDrug 간 성분 중복 여부 (단일제 vs 복합제 교차 포함)."""
    return bool(_find_overlapping_ingredients(drug1, drug2))


# 금기 drug_class 기반 Lab 규칙 — (check_fn, reason, risk_level)
_LAB_SAFETY_RULES: list[tuple] = [
    (lambda d, lab: d.drug_class == "biguanide" and (lab.get("egfr") or 999) < 30,
     "eGFR < 30 — Metformin 금기 (락트산산증)", "contraindicated"),
    (lambda d, lab: d.drug_class == "biguanide" and 30 <= (lab.get("egfr") or 999) < 45,
     "eGFR 30~44 — Metformin 감량 필요", "moderate"),
    (lambda d, lab: d.drug_class in ("NSAID", "COX2") and (lab.get("egfr") or 999) < 30,
     "eGFR < 30 — NSAIDs 금기 (신기능 악화)", "contraindicated"),
    (lambda d, lab: d.drug_class in ("NSAID", "COX2") and (lab.get("egfr") or 999) < 60,
     "eGFR < 60 — NSAIDs 신기능 악화 위험", "high"),
    (lambda d, lab: d.drug_class in ("SGLT2",) and (lab.get("egfr") or 999) < 20,
     "eGFR < 20 — SGLT2i 금기", "contraindicated"),
    (lambda d, lab: d.drug_class in ("NOAC",) and (lab.get("egfr") or 999) < 15,
     "eGFR < 15 — NOAC 금기", "contraindicated"),
    (lambda d, lab: d.drug_class in ("ACEI", "ARB", "K-sparing") and (lab.get("potassium") or 0) > 5.5,
     "K⁺ > 5.5 — ACEI/ARB/MRA 금기 수준 고칼륨혈증", "contraindicated"),
    (lambda d, lab: d.drug_class in ("ACEI", "ARB", "K-sparing") and (lab.get("potassium") or 0) > 5.0,
     "K⁺ > 5.0 — 고칼륨혈증 주의", "high"),
    (lambda d, lab: d.drug_class == "fluoroquinolone" and (lab.get("qtc") or 0) > 450,
     "QTc > 450ms — fluoroquinolone QT 연장 금기", "contraindicated"),
    (lambda d, lab: d.drug_class == "macrolide" and (lab.get("qtc") or 0) > 450,
     "QTc > 450ms — macrolide QT 연장 위험", "high"),
    (lambda d, lab: d.drug_class == "antipsychotic-SGA" and (lab.get("qtc") or 0) > 470,
     "QTc > 470ms — 항정신병약 QT 연장 주의", "high"),
]

# 고령 안전성 경고 (is_eligible 변경 없이 warnings 추가)
_ELDERLY_WARNINGS: list[tuple] = [
    (lambda d, age: d.drug_class == "BZD" and (age or 0) >= 65,
     "고령(≥65세) + BZD — Beers 2023: 낙상·섬망 위험"),
    (lambda d, age: d.drug_class == "Z-drug" and (age or 0) >= 65,
     "고령(≥65세) + Z-drug(졸피뎀 등) — 낙상·인지 위험"),
    (lambda d, age: d.drug_class == "TCA" and (age or 0) >= 65,
     "고령(≥65세) + TCA — 항콜린성 부작용·낙상 위험 (Beers 2023)"),
    (lambda d, age: d.drug_class == "antihistamine-1gen" and (age or 0) >= 65,
     "고령(≥65세) + 1세대 항히스타민 — 인지·낙상 위험 (Beers 2023)"),
    (lambda d, age: d.drug_class in ("NSAID", "COX2") and (age or 0) >= 65,
     "고령(≥65세) + NSAIDs — GI출혈·신독성·심혈관 위험 증가 (Beers 2023)"),
]

# DDI 쌍별 즉시 금기 클래스 조합 (contraindicated 수준)
_DDI_CONTRAINDICATED_PAIRS: list[tuple[str, str, str]] = [
    ("NOAC", "anticoagulant", "NOAC + 항응고제 중복 — 치명적 출혈 위험"),
    ("NOAC", "NOAC", "NOAC 중복 처방 — 치명적 출혈 위험"),
    ("ACEI", "ARB", "ACEI + ARB 이중 RAAS — 고칼륨혈증·급성신부전 위험"),
    ("fluoroquinolone", "macrolide", "Fluoroquinolone + Macrolide — TdP(치명적 부정맥) 위험"),
]
# DDI 고위험 클래스 조합
_DDI_HIGH_PAIRS: list[tuple[str, str, str]] = [
    ("NSAID", "anticoagulant", "NSAID + 항응고제 — GI 출혈 위험"),
    ("NSAID", "NOAC", "NSAID + NOAC — GI 출혈 위험 2~4배"),
    ("SSRI", "NSAID", "SSRI + NSAID — 상부 GI 출혈 위험 15배"),
    ("SNRI", "NSAID", "SNRI + NSAID — 상부 GI 출혈 위험"),
    ("statin", "macrolide", "Statin + Macrolide — CYP3A4 억제, 횡문근융해증"),
    ("BZD", "opioid", "BZD + Opioid — 호흡억제·사망 위험 (FDA Black Box)"),
    ("K-sparing", "ACEI", "MRA + ACEI — 고칼륨혈증"),
    ("K-sparing", "ARB", "MRA + ARB — 고칼륨혈증"),
]


def _parse_note_fields(physician_note: str) -> tuple[list[str], list[str]]:
    """physician_note에서 증상 태그, 진단명 태그 추출."""
    symptoms: list[str] = []
    diagnoses: list[str] = []
    for line in physician_note.splitlines():
        m_sym = _SECTION_SYM_RE.match(line.strip())
        if m_sym:
            val = next(g for g in m_sym.groups() if g)
            symptoms.extend(t.strip() for t in re.split(r"[,，、]", val) if t.strip())
        m_diag = re.match(r"진단명\s*[:：]\s*(.+)", line.strip(), re.IGNORECASE)
        if m_diag:
            diagnoses.extend(t.strip() for t in re.split(r"[,，、]", m_diag.group(1)) if t.strip())
    return symptoms, diagnoses


def _extract_context_tags(lines: list[str], current_idx: int) -> tuple[list[str], list[str]]:
    """약물 라인 앞 3줄에서 섹션 헤더로부터 증상/진단 태그를 추출한다."""
    symptoms: list[str] = []
    diagnoses: list[str] = []
    start = max(0, current_idx - 3)
    for line in lines[start:current_idx]:
        m_d = _SECTION_DIAG_RE.match(line.strip())
        if m_d:
            val = next((g for g in m_d.groups() if g), "")
            diagnoses.extend(t.strip() for t in re.split(r"[,，、]", val) if t.strip())
        m_s = _SECTION_SYM_RE.match(line.strip())
        if m_s:
            val = next((g for g in m_s.groups() if g), "")
            symptoms.extend(t.strip() for t in re.split(r"[,，、]", val) if t.strip())
    return symptoms, diagnoses


# ──────────────────────────────────────────────────────────────────────────────
# 공개 함수
# ──────────────────────────────────────────────────────────────────────────────

def parse_prescription_history(
    history_text: str,
    recent_logs: list | None = None,
) -> list[HistoryDrug]:
    """EMR 텍스트 + PrescriptionLog 리스트 → HistoryDrug 리스트."""
    results: list[HistoryDrug] = []
    seen_keys: set[str] = set()  # 중복 제거용 (normalized_name + date)

    # ── EMR 텍스트 파싱 ──────────────────────────────────────────────────────
    if history_text:
        lines = [l for l in history_text.splitlines() if l.strip()]
        for idx, line in enumerate(lines):
            # 날짜 추출
            date_str: str | None = None
            dm = _DATE_RE.search(line)
            if dm:
                date_str = f"{dm.group(1)}-{dm.group(2).zfill(2)}-{dm.group(3).zfill(2)}"

            # 약물명 후보: 날짜·용량·복용법·구두점 제거 후 남은 텍스트
            clean = _DATE_RE.sub("", line)
            clean = _STRENGTH_RE.sub("", clean)
            clean = _FREQ_RE.sub("", clean)
            clean = re.sub(r"[#\-·•→:\[\]()（）]", " ", clean)
            clean = re.sub(r"\s+", " ", clean).strip()

            # 각 단어 토큰에서 약물명 후보 탐색
            tokens = clean.split()
            candidate_names: list[str] = []
            i = 0
            while i < len(tokens):
                t = tokens[i]
                # 비약물 토큰(효과 지시어·복용법 잔여·용량 잔여 등) 건너뜀
                if _is_non_drug_history_token(t):
                    i += 1
                    continue
                # 2토큰 복합 시도 — 두 번째 토큰도 비약물 토큰이 아닐 때만
                if i + 1 < len(tokens) and not _is_non_drug_history_token(tokens[i + 1]):
                    two = t + " " + tokens[i + 1]
                    nd = normalize_drug_name(two)
                    if nd.ingredient_code is not None or nd.normalized_name != two:
                        candidate_names.append(two)
                        i += 2
                        continue
                # 단일 토큰
                nd = normalize_drug_name(t)
                if nd.ingredient_code is not None or nd.normalized_name != t:
                    candidate_names.append(t)
                i += 1

            if not candidate_names:
                continue

            # 용량·복용법
            sm = _STRENGTH_RE.search(line)
            strength = sm.group(0) if sm else None
            fm = _FREQ_RE.search(line)
            frequency = fm.group(0) if fm else None

            # 효과/부작용
            adverse = bool(_ADVERSE_RE.search(line))
            adverse_reason: str | None = None
            if adverse:
                am = _ADVERSE_RE.search(line)
                adverse_reason = am.group(0) if am else None
            effect: str = "unknown"
            if _EFFECT_POSITIVE.search(line):
                effect = "effective"
            elif _EFFECT_NEGATIVE.search(line) or adverse:
                effect = "ineffective"

            # 컨텍스트 태그 (앞 줄 헤더)
            ctx_sym, ctx_diag = _extract_context_tags(lines, idx)

            for raw_name in candidate_names:
                nd = normalize_drug_name(raw_name)
                dedup_key = f"{nd.normalized_name}|{date_str or ''}"
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                results.append(HistoryDrug(
                    source="emr_text",
                    date=date_str,
                    raw_name=raw_name,
                    normalized_name=nd.normalized_name,
                    ingredient_code=nd.ingredient_code,
                    ingredient_names=nd.ingredient_names,
                    strength=strength,
                    frequency=frequency,
                    symptom_tags=ctx_sym,
                    diagnosis_tags=ctx_diag,
                    effect_status=effect,
                    adverse_event=adverse,
                    adverse_reason=adverse_reason,
                ))

    # ── PrescriptionLog 파싱 ────────────────────────────────────────────────
    for log in (recent_logs or []):
        raw_name = getattr(log, "recommended_generic_name_ko", "") or ""
        if not raw_name:
            continue

        date_str = None
        if hasattr(log, "created_at") and log.created_at:
            date_str = log.created_at.strftime("%Y-%m-%d")

        nd = normalize_drug_name(raw_name)
        dedup_key = f"{nd.normalized_name}|{date_str or ''}"
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        strength_mg = getattr(log, "recommended_strength_mg", None)
        strength = f"{strength_mg}mg" if strength_mg else None
        frequency = getattr(log, "recommended_frequency", None)

        # physician_notes에서 증상/진단 태그 파싱
        notes_text = getattr(log, "physician_notes", "") or ""
        sym_tags, diag_tags = _parse_note_fields(notes_text)

        results.append(HistoryDrug(
            source="prescription_log",
            date=date_str,
            raw_name=raw_name,
            normalized_name=nd.normalized_name,
            ingredient_code=nd.ingredient_code,
            ingredient_names=nd.ingredient_names,
            strength=strength,
            frequency=frequency,
            symptom_tags=sym_tags,
            diagnosis_tags=diag_tags,
            effect_status="unknown",
            adverse_event=False,
            adverse_reason=None,
        ))

    return results


def _normalize_disease_keys(value) -> list[str]:
    """dict/list/tuple/set/str/None → 질환 키 리스트로 안전하게 변환."""
    if value is None:
        return []
    if isinstance(value, dict):
        return [k for k, v in value.items() if v is True]
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if isinstance(item, str)]
    if isinstance(value, str):
        return [value] if value else []
    return []


def match_history_to_current_visit(
    history_drugs: list[HistoryDrug],
    physician_note: str,
    disease_updates,
    patient_diseases,
) -> list[HistoryMatch]:
    """현재 진료 컨텍스트와 과거 처방약의 증상/진단 일치도 계산."""
    current_symptoms, current_diagnoses = _parse_note_fields(physician_note)

    # disease_updates / patient_diseases → 진단명 태그로 변환 (dict·list·None 모두 허용)
    all_disease_keys: list[str] = []
    all_disease_keys.extend(_normalize_disease_keys(disease_updates))
    all_disease_keys.extend(_normalize_disease_keys(patient_diseases))
    all_disease_keys = list(dict.fromkeys(all_disease_keys))

    results: list[HistoryMatch] = []
    for hd in history_drugs:
        score = 0.0
        match_type = "none"
        reasons: list[str] = []

        # 진단명 매칭 (weight 1.0)
        for cd in current_diagnoses:
            for dt in hd.diagnosis_tags:
                if cd and dt and (cd in dt or dt in cd):
                    score = max(score, 1.0)
                    match_type = "same_diagnosis"
                    reasons.append(f"과거 동일 진단명({dt}) 처방 확인")

        # 증상 매칭 (weight 0.7)
        if score < 0.7:
            for cs in current_symptoms:
                for st in hd.symptom_tags:
                    if cs and st and (cs in st or st in cs):
                        score = max(score, 0.7)
                        if match_type == "none":
                            match_type = "same_symptom"
                        reasons.append(f"과거 동일 증상({st}) 처방 확인")

        # disease_key 기반 간접 매칭 (weight 0.5) — normalized_name 또는 drug_class 기반
        if score < 0.5:
            # 불면 계열: 진단명 "불면증" ↔ drug_class in (BZD, Z-drug, SARI, NaSSA, melatonin-agonist)
            sleepless_classes = {"BZD", "Z-drug", "SARI", "NaSSA", "melatonin-agonist"}
            sleepless_diags = {"insomnia", "불면증", "수면장애", "sleep disorder"}
            nd = normalize_drug_name(hd.raw_name)
            if nd.drug_class in sleepless_classes:
                if any(d in " ".join(current_diagnoses).lower() for d in sleepless_diags):
                    score = max(score, 0.5)
                    match_type = "partial"
                    reasons.append("수면 관련 약물 — 현재 불면 진단과 부분 일치")

            # 우울/불안 계열
            mood_classes = {"SSRI", "SNRI", "TCA", "SARI", "NaSSA"}
            mood_diags = {"depression", "우울증", "anxiety", "불안장애", "공황장애"}
            if nd.drug_class in mood_classes:
                if any(d in " ".join(current_diagnoses).lower() for d in mood_diags):
                    score = max(score, 0.5)
                    match_type = "partial"
                    reasons.append("항우울/항불안 약물 — 현재 기분장애 진단과 부분 일치")

            # 항정신병 계열
            ap_classes = {"antipsychotic-SGA", "antipsychotic-FGA"}
            ap_diags = {"schizophrenia", "조현병", "bipolar", "양극성", "psychosis", "정신증"}
            if nd.drug_class in ap_classes:
                if any(d in " ".join(current_diagnoses).lower() for d in ap_diags):
                    score = max(score, 0.5)
                    match_type = "partial"
                    reasons.append("항정신병약 — 현재 정신증/조현병 진단과 부분 일치")

        if score < 0.3:
            # 완전 정규화 실패(성분코드·drug_class 모두 없음) → 수동 확인 가점
            _nd_fb = normalize_drug_name(hd.raw_name)
            if _nd_fb.ingredient_code is None and _nd_fb.drug_class is None:
                score = 0.1
                match_type = "none"
                reasons = [f"미등재 약물 — 수동 확인 필요: {hd.raw_name}"]
            else:
                continue

        results.append(HistoryMatch(
            history_drug=hd,
            match_type=match_type,
            match_score=round(score, 2),
            reason=" / ".join(dict.fromkeys(reasons)) if reasons else f"매칭 점수 {score:.1f}",
        ))

    return sorted(results, key=lambda m: m.match_score, reverse=True)


def _get_drug_class_for_safety(hd: HistoryDrug) -> str | None:
    """HistoryDrug → drug_class 반환 (normalize 재시도 포함)."""
    nd = normalize_drug_name(hd.raw_name)
    return nd.drug_class


def evaluate_history_drug_safety(
    matched_history: list[HistoryMatch],
    current_drugs: list[NormalizedDrug],
    allergies: list[str],
    lab_values: dict | None,
    feedbacks: list | None,
) -> list[HistorySafetyResult]:
    """과거 처방약의 현재 안전성 판정."""
    lab = lab_values or {}
    fb_adverse: set[str] = set()
    if feedbacks:
        for f in feedbacks:
            if getattr(f, "feedback_type", "") == "adverse_event":
                name_ko = getattr(f, "affected_generic_ko", "") or ""
                name_en = getattr(f, "affected_generic_en", "") or ""
                if name_ko:
                    fb_adverse.add(normalize_drug_name(name_ko).normalized_name.lower())
                if name_en:
                    fb_adverse.add(normalize_drug_name(name_en).normalized_name.lower())

    results: list[HistorySafetyResult] = []

    for match in matched_history:
        hd = match.history_drug
        nd = normalize_drug_name(hd.raw_name)
        drug_class = nd.drug_class or ""
        exclude_reasons: list[str] = []
        warnings_out: list[str] = []
        risk_level = "low"

        # ① 과거 부작용 기록
        if hd.adverse_event:
            reason = hd.adverse_reason or "부작용"
            exclude_reasons.append(f"과거 부작용 기록: {reason}")
            risk_level = "contraindicated"

        # ② Feedback 부작용 이력
        if nd.normalized_name.lower() in fb_adverse:
            exclude_reasons.append("처방 이력에 부작용·의사 수정 기록 존재")
            risk_level = "contraindicated"

        # ③ 알레르기
        for allergy in (allergies or []):
            allergy_nd = normalize_drug_name(allergy)
            if (
                allergy_nd.normalized_name.lower() == nd.normalized_name.lower()
                or any(
                    a.lower() in nd.ingredient_names
                    for a in allergy_nd.ingredient_names
                )
            ):
                exclude_reasons.append(f"알레르기 이력: {allergy}")
                risk_level = "contraindicated"

        # ④ Lab 기반 금기 — 복합제의 경우 각 성분 약물도 개별 체크
        if not exclude_reasons:
            for check_nd in _iter_drug_and_components(nd):
                for rule_fn, reason, rule_risk in _LAB_SAFETY_RULES:
                    try:
                        if rule_fn(check_nd, lab):
                            if rule_risk == "contraindicated":
                                exclude_reasons.append(reason)
                                risk_level = "contraindicated"
                            elif rule_risk == "high":
                                if risk_level not in ("contraindicated",):
                                    risk_level = "high"
                                warnings_out.append(reason)
                            elif rule_risk == "moderate":
                                if risk_level == "low":
                                    risk_level = "moderate"
                                warnings_out.append(reason)
                    except Exception:
                        pass

        # ⑤ 현재 복용약과 성분 중복 + DDI 체크
        if not exclude_reasons:
            for current in current_drugs:
                # ⑤-a 성분 중복 (단일제 vs 복합제 교차 포함)
                _overlap = _find_overlapping_ingredients(nd, current)
                if _overlap:
                    _overlap_str = "·".join(_overlap)
                    exclude_reasons.append(
                        f"성분 중복: {current.normalized_name} 내 [{_overlap_str}] 중복 처방 위험"
                    )
                    risk_level = "contraindicated"
                # ⑤-b 약물 상호작용 (drug_class 기반)
                for cls_a, cls_b, ddi_reason in _DDI_CONTRAINDICATED_PAIRS:
                    classes = {drug_class, current.drug_class or ""}
                    if cls_a in classes and cls_b in classes:
                        exclude_reasons.append(f"현재 복용약({current.normalized_name})과 DDI: {ddi_reason}")
                        risk_level = "contraindicated"
                for cls_a, cls_b, ddi_reason in _DDI_HIGH_PAIRS:
                    classes = {drug_class, current.drug_class or ""}
                    if cls_a in classes and cls_b in classes:
                        if risk_level not in ("contraindicated",):
                            risk_level = "high"
                        warnings_out.append(f"DDI 주의({current.normalized_name}): {ddi_reason}")

        # ⑥ 고령 안전성 경고 (is_eligible 변경 없음)
        age = lab.get("_patient_age")  # router에서 lab_values에 임시 주입
        for rule_fn, warn_msg in _ELDERLY_WARNINGS:
            try:
                if rule_fn(nd, age):
                    warnings_out.append(warn_msg)
                    if risk_level == "low":
                        risk_level = "moderate"
            except Exception:
                pass

        is_eligible = len(exclude_reasons) == 0
        results.append(HistorySafetyResult(
            match=match,
            is_eligible=is_eligible,
            risk_level=risk_level if not is_eligible else risk_level,
            exclude_reasons=exclude_reasons,
            warnings=warnings_out,
        ))

    return results


def enforce_history_priority(
    recommendation_set: RecommendationSet,
    prescription_set: list[RecommendedGeneric],
    eligible_history: list[HistorySafetyResult],
) -> tuple[RecommendationSet, list[str], HistoryPriorityInfo]:
    """안전한 과거 처방약을 primary 최상단에 강제 배치.

    Returns:
        (수정된 RecommendationSet, 추가 warnings 리스트, HistoryPriorityInfo)
    """
    extra_warnings: list[str] = []
    promoted: list[PromotedHistoryItem] = []
    excluded: list[ExcludedHistoryItem] = []

    # 제외된 약물 → warnings
    for result in eligible_history:
        if not result.is_eligible and result.exclude_reasons:
            hd = result.match.history_drug
            reason = result.exclude_reasons[0]
            extra_warnings.append(f"[제외된 기존 처방] {hd.normalized_name}: {reason}")
            excluded.append(ExcludedHistoryItem(name=hd.normalized_name, reason=reason))

    # 안전한 후보 정렬: match_score 내림차순 → effective > unknown → risk_level
    _risk_ord = {"low": 3, "moderate": 2, "high": 1, "contraindicated": 0}
    _effect_ord = {"effective": 2, "unknown": 1, "ineffective": 0}
    safe_candidates = [r for r in eligible_history if r.is_eligible]
    safe_candidates.sort(
        key=lambda r: (
            r.match.match_score,
            _effect_ord.get(r.match.history_drug.effect_status, 1),
            _risk_ord.get(r.risk_level, 0),
        ),
        reverse=True,
    )

    # 최대 2개만 primary 최상단에 배치
    primary = list(recommendation_set.primary)
    secondary = list(recommendation_set.secondary)
    prepend_items: list[RxItem] = []

    for result in safe_candidates[:2]:
        hd = result.match.history_drug
        nd = normalize_drug_name(hd.raw_name)

        effect_label = {"effective": "효과 있음", "ineffective": "효과 없음", "unknown": "효과 미상"}.get(
            hd.effect_status, "효과 미상"
        )
        match_label = "동일 진단" if result.match.match_type == "same_diagnosis" else "동일 증상"
        note_text = (
            f"[기존 처방 재검토] 과거 {match_label} 처방 — {effect_label}"
        )
        if result.warnings:
            note_text += f" ⚠ {result.warnings[0]}"

        # 이미 primary에 동일 성분이 있으면 → 해당 항목을 맨 앞으로 이동
        existing_idx = next(
            (
                i for i, rx in enumerate(primary)
                if _is_same_drug(rx.generic_name_ko, nd)
            ),
            None,
        )
        if existing_idx is not None:
            existing = primary.pop(existing_idx)
            updated = RxItem(
                generic_name_ko=existing.generic_name_ko,
                strength=existing.strength or hd.strength or "",
                frequency=existing.frequency or hd.frequency or "",
                form_description=existing.form_description,
                category=existing.category,
                note=note_text,
            )
            prepend_items.append(updated)
        else:
            # 새 항목 prepend
            prepend_items.append(RxItem(
                generic_name_ko=nd.normalized_name,
                strength=hd.strength or "",
                frequency=hd.frequency or "",
                form_description="",
                category="주치료",
                note=note_text,
            ))

        promoted.append(PromotedHistoryItem(
            name=nd.normalized_name,
            reason=result.match.reason,
        ))

    # prepend → primary 앞에 배치, 최대 6개 유지
    new_primary = (prepend_items + primary)[:6]

    history_info = HistoryPriorityInfo(
        promoted=promoted,
        excluded=excluded,
        matched_count=len(eligible_history),
    )

    return (
        RecommendationSet(primary=new_primary, secondary=secondary),
        extra_warnings,
        history_info,
    )


def _is_same_drug(rx_name_ko: str, nd: NormalizedDrug) -> bool:
    """RxItem의 generic_name_ko와 NormalizedDrug이 같은 성분인지 비교."""
    rx_nd = normalize_drug_name(rx_name_ko)
    # normalized_name 일치
    if rx_nd.normalized_name.lower() == nd.normalized_name.lower():
        return True
    # ingredient_code 일치 (ATC)
    if rx_nd.ingredient_code and nd.ingredient_code:
        if rx_nd.ingredient_code == nd.ingredient_code:
            return True
    # ingredient_names 교집합
    rx_ings = {n.lower() for n in rx_nd.ingredient_names}
    nd_ings = {n.lower() for n in nd.ingredient_names}
    return bool(rx_ings & nd_ings)
