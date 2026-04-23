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
