import pytest
import uuid
from sqlalchemy import select
from app.models.patient import PatientProfile, DiseaseFlags, LabValues
from app.models.drug import DrugKnowledgeBase
from app.models.prescription import PrescriptionLog
from app.models.feedback import PrescriptionFeedback


@pytest.mark.asyncio
async def test_create_adverse_event_feedback(db_session):
    patient = PatientProfile(
        patient_code="PT-FB-001", age=70, gender="F",
        diseases=DiseaseFlags(hypertension=True).model_dump(),
        lab_values=LabValues().model_dump(), allergies=[],
    )
    drug = DrugKnowledgeBase(
        generic_name_ko="에날라프릴", generic_name_en="Enalapril",
        drug_class="ACE inhibitor", indications=["고혈압"],
        contraindications={"absolute": [], "relative": []},
        standard_dosage={"initial": {"dose_mg": 5, "frequency": "BID", "route": "PO"}, "max_daily_mg": 40},
        dose_forms=["tablet"], strengths_available_mg=[5, 10],
        guideline_source="ESC 2023", guideline_year=2023,
        special_populations={}, monitoring_parameters=[],
    )
    db_session.add_all([patient, drug])
    await db_session.flush()

    log = PrescriptionLog(
        patient_id=patient.id, session_id=uuid.uuid4(), drug_id=drug.id,
        recommended_generic_name_ko="에날라프릴",
        recommended_generic_name_en="Enalapril",
        recommended_strength_mg=5.0,
        recommended_dose_description="5mg 1정",
        recommended_frequency="BID",
        clinical_rationale="고혈압 치료",
        warnings=[],
    )
    db_session.add(log)
    await db_session.flush()

    feedback = PrescriptionFeedback(
        prescription_log_id=log.id,
        patient_id=patient.id,
        feedback_type="adverse_event",
        severity="severe",
        description="혈관부종 발생",
        affected_generic_ko="에날라프릴",
        affected_generic_en="Enalapril",
        recorded_by="Dr.Kim",
    )
    db_session.add(feedback)
    await db_session.commit()
    await db_session.refresh(feedback)

    result = await db_session.execute(
        select(PrescriptionFeedback).where(PrescriptionFeedback.patient_id == patient.id)
    )
    saved = result.scalar_one()
    assert saved.feedback_type == "adverse_event"
    assert saved.severity == "severe"
    assert saved.affected_generic_en == "Enalapril"
