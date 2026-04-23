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
