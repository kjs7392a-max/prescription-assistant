import pytest
from sqlalchemy import select
from app.models.patient import PatientProfile, DiseaseFlags, LabValues

@pytest.mark.asyncio
async def test_create_patient_profile(db_session):
    patient = PatientProfile(
        patient_code="PT-001",
        age=65,
        gender="M",
        weight_kg=72.0,
        height_cm=170.0,
        diseases=DiseaseFlags(
            hypertension=True,
            diabetes_type2=True,
            ckd=True,
            ckd_stage=3,
        ).model_dump(),
        lab_values=LabValues(
            creatinine=1.8,
            egfr=38.0,
            hba1c=7.2,
            fasting_glucose=145.0,
            ldl=112.0,
            hdl=45.0,
            total_cholesterol=198.0,
        ).model_dump(),
        allergies=["penicillin"],
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    result = await db_session.execute(
        select(PatientProfile).where(PatientProfile.patient_code == "PT-001")
    )
    saved = result.scalar_one()
    assert saved.diseases["hypertension"] is True
    assert saved.lab_values["egfr"] == 38.0
    assert "penicillin" in saved.allergies
