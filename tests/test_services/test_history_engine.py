"""TC-01~TC-06: history_engine 결정론적 re-ranking 단위 테스트."""
import pytest
from app.schemas.history import NormalizedDrug
from app.schemas.inference import RxItem, RecommendationSet
from app.services.history_engine import (
    parse_prescription_history,
    match_history_to_current_visit,
    evaluate_history_drug_safety,
    enforce_history_priority,
    is_duplicate_ingredient,
)
from app.services.drug_normalizer import normalize_drug_name


# ── 공통 헬퍼 ─────────────────────────────────────────────────────────────────

def _make_rec_set(*names: str) -> RecommendationSet:
    primary = [RxItem(generic_name_ko=n, category="주치료") for n in names]
    return RecommendationSet(primary=primary)


# ── TC-01: 동일 진단 과거 처방 → primary[0] 강제 배치 ───────────────────────

def test_tc01_same_diagnosis_promoted_to_top():
    """과거 '불면증' 진단에 효과 있던 Trazodone → 현재 불면증 진단 시 primary[0] 배치."""
    # 다중행 형식: 진단 헤더가 약물 라인 앞에 위치해야 diagnosis_tags로 파싱됨
    history_text = "진단: 불면증\n2024-01-10 트라조돈 50mg HS 효과있음"
    history_drugs = parse_prescription_history(history_text, [])
    assert history_drugs, "히스토리 파싱 실패"
    assert history_drugs[0].normalized_name == "트라조돈"

    matched = match_history_to_current_visit(
        history_drugs,
        physician_note="증상: 불면\n진단명: 불면증",
        disease_updates={},
        patient_diseases=[],
    )
    assert matched, "매칭 실패"
    # 진단명 기반 일치 또는 drug_class 기반 partial 모두 허용
    assert matched[0].match_type in ("same_diagnosis", "same_symptom", "partial"), (
        f"예상치 못한 match_type: {matched[0].match_type}"
    )

    safety = evaluate_history_drug_safety(matched, [], [], {}, [])
    eligible = [r for r in safety if r.is_eligible]
    assert eligible, "eligible 없음"

    # 현재 추천셋에 트라조돈 없음 → prepend 되어 primary[0]이 되어야 함
    rec_set = _make_rec_set("에스시탈로프람", "미르타자핀", "쿠에티아핀")
    new_set, _, info = enforce_history_priority(rec_set, [], eligible)

    assert new_set.primary[0].generic_name_ko == "트라조돈", (
        f"primary[0] 기대: 트라조돈, 실제: {new_set.primary[0].generic_name_ko}"
    )
    assert info.matched_count >= 1


# ── TC-02: 부작용 이력 → 추천 목록 제외 ────────────────────────────────────

def test_tc02_adverse_event_excluded():
    """과거 리스페리돈 낙상 부작용 이력 → eligible=False, exclude_reasons 비어있지 않음."""
    # 진단 헤더 + 부작용 키워드 포함 약물 라인
    history_text = "진단: 조현병\n2023-06-15 리스페리돈 2mg QHS 낙상 부작용"
    history_drugs = parse_prescription_history(history_text, [])
    assert history_drugs, "히스토리 파싱 실패"

    matched = match_history_to_current_visit(
        history_drugs,
        physician_note="증상: 환청\n진단명: 조현병",
        disease_updates={},
        patient_diseases=[],
    )
    assert matched, "매칭 실패"

    safety = evaluate_history_drug_safety(matched, [], [], {}, [])
    assert safety
    excluded = [r for r in safety if not r.is_eligible]
    assert excluded, "부작용 이력 약물이 eligible=True로 통과됨"
    assert excluded[0].exclude_reasons, "exclude_reasons 비어있음"


# ── TC-03: eGFR < 30 + Metformin → 금기 판정 ────────────────────────────────

def test_tc03_metformin_egfr_contraindicated():
    """eGFR 25 환자에게 Metformin → risk_level='contraindicated'."""
    history_text = "진단: 당뇨병\n2024-03-01 메트포르민 500mg BID 효과있음"
    history_drugs = parse_prescription_history(history_text, [])
    assert history_drugs, "히스토리 파싱 실패"

    matched = match_history_to_current_visit(
        history_drugs,
        physician_note="증상: 혈당조절불량\n진단명: 당뇨병",
        disease_updates={},
        patient_diseases=["diabetes_type2"],
    )
    assert matched, "매칭 실패"

    safety = evaluate_history_drug_safety(
        matched,
        current_drugs=[],
        allergies=[],
        lab_values={"egfr": 25},
        feedbacks=[],
    )
    assert safety
    result = safety[0]
    assert result.risk_level == "contraindicated", (
        f"기대: contraindicated, 실제: {result.risk_level}"
    )
    assert not result.is_eligible


# ── TC-04: 복합제(글루코파지) 성분 분리 → 메트포르민 기반 매칭 ─────────────

def test_tc04_combination_drug_ingredient_matching():
    """'글루코파지'(메트포르민 제품명)를 성분명 '메트포르민'으로 정규화."""
    from app.services.drug_normalizer import normalize_drug_name

    nd = normalize_drug_name("글루코파지")
    assert nd.normalized_name == "메트포르민", (
        f"normalized_name 기대: 메트포르민, 실제: {nd.normalized_name}"
    )
    assert nd.ingredient_code == "A10BA02", (
        f"ingredient_code 기대: A10BA02, 실제: {nd.ingredient_code}"
    )

    # 히스토리에 '글루코파지'로 입력 → 내부적으로 메트포르민으로 정규화
    history_text = "진단: 당뇨\n2024-01-01 글루코파지 500mg QD 효과있음"
    history_drugs = parse_prescription_history(history_text, [])
    assert history_drugs, "히스토리 파싱 실패"
    assert history_drugs[0].normalized_name == "메트포르민", (
        f"정규화 실패: {history_drugs[0].normalized_name}"
    )
    assert history_drugs[0].ingredient_code == "A10BA02"


# ── TC-05: 증상 기반 부분 매칭 → same_symptom 또는 partial 처리 ──────────────

def test_tc05_partial_match_by_symptom():
    """과거 '우울' 증상 처방 서트랄린 → 현재 '불안·우울' 진료 시 same_symptom/partial 매칭."""
    history_text = "증상: 우울\n2023-11-20 서트랄린 50mg QD 효과있음"
    history_drugs = parse_prescription_history(history_text, [])
    assert history_drugs, "히스토리 파싱 실패"
    assert history_drugs[0].normalized_name == "서트랄린"
    assert "우울" in history_drugs[0].symptom_tags

    matched = match_history_to_current_visit(
        history_drugs,
        physician_note="증상: 불안 우울\n진단명: 불안장애",
        disease_updates={},
        patient_diseases=[],
    )
    assert matched, "매칭 결과 없음"
    match_types = {m.match_type for m in matched}
    assert match_types & {"same_symptom", "partial"}, (
        f"기대: same_symptom 또는 partial, 실제: {match_types}"
    )
    # 최상위 매칭 스코어가 임계값 이상인지 확인
    assert matched[0].match_score >= 0.3


# ── TC-06: 3제 복합제 vs 단일제/2제 복합제 성분 중복 탐지 ──────────────────────

def test_tc06_triple_combination_duplicate_ingredient_detection():
    """3제 복합제(암로디핀+로사르탄+클로르탈리돈) 히스토리 시나리오.

    해당 3제 복합제에 포함된 임의의 1개 성분이 현재 처방 제안(단일제 또는 2제 복합제)에
    있을 때 is_duplicate_ingredient가 True를 반환해야 한다.
    무관한 성분에 대해서는 False를 반환해야 한다.
    """
    # 3제 복합제 직접 구성 (클로르탈리돈은 DB 미등재 성분이므로 수동 구성)
    triple_combo = NormalizedDrug(
        raw_name="암로디핀/로사르탄/클로르탈리돈",
        normalized_name="암로디핀 / 로사르탄 / 클로르탈리돈",
        ingredient_code=None,
        ingredient_names=[
            "amlodipine", "losartan", "chlorthalidone",
            "암로디핀", "로사르탄", "클로르탈리돈",
        ],
        drug_class="CCB+ARB+thiazide",
        is_combination=True,
        components=["amlodipine", "losartan", "chlorthalidone"],
    )

    # ① 3제 vs 단일제(암로디핀) — 공유 성분 amlodipine
    single_amlodipine = normalize_drug_name("암로디핀")
    assert single_amlodipine.ingredient_code == "C08CA01", "암로디핀 정규화 실패"
    assert is_duplicate_ingredient(triple_combo, single_amlodipine), (
        "3제 복합제 vs 단일제(암로디핀) 성분 중복 탐지 실패"
    )

    # ② 3제 vs 2제 복합제(암로디핀+로사르탄, 로바티) — 공유 성분 amlodipine+losartan
    double_combo = normalize_drug_name("로바티")
    assert double_combo.is_combination, "로바티(암로디핀+로사르탄 복합제) 정규화 실패"
    assert is_duplicate_ingredient(triple_combo, double_combo), (
        "3제 복합제 vs 2제 복합제(로바티) 성분 중복 탐지 실패"
    )

    # ③ 3제 vs 단일제(클로르탈리돈, DB 미등재) — ingredient_names 교집합으로 탐지
    single_chlorthalidone = NormalizedDrug(
        raw_name="클로르탈리돈",
        normalized_name="클로르탈리돈",
        ingredient_code=None,
        ingredient_names=["chlorthalidone", "클로르탈리돈"],
        drug_class="thiazide",
        is_combination=False,
        components=[],
    )
    assert is_duplicate_ingredient(triple_combo, single_chlorthalidone), (
        "3제 복합제 vs 단일제(클로르탈리돈, DB 미등재) 성분 중복 탐지 실패"
    )

    # ④ 3제 vs 무관한 약물(에스시탈로프람) — 오탐지 방지
    unrelated = normalize_drug_name("에스시탈로프람")
    assert not is_duplicate_ingredient(triple_combo, unrelated), (
        "3제 복합제 vs 무관한 약물(에스시탈로프람) 오탐지 발생"
    )
