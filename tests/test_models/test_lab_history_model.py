import pytest
from datetime import datetime
from sqlalchemy import select
from app.models.patient import PatientProfile, DiseaseFlags, LabValues
from app.models.lab_history import PatientLabHistory

@pytest.mark.asyncio
async def test_create_lab_history_snapshot(db_session):
    patient = PatientProfile(
        patient_code="PT-LAB-001",
        age=65, gender="M",
        diseases=DiseaseFlags(ckd=True).model_dump(),
        lab_values=LabValues(egfr=60.0).model_dump(),
        allergies=[],
    )
    db_session.add(patient)
    await db_session.flush()

    snap1 = PatientLabHistory(
        patient_id=patient.id,
        recorded_at=datetime(2026, 2, 1),
        lab_values={"egfr": 60.0, "creatinine": 1.2},
        source="manual",
    )
    snap2 = PatientLabHistory(
        patient_id=patient.id,
        recorded_at=datetime(2026, 3, 1),
        lab_values={"egfr": 55.0, "creatinine": 1.4},
        source="manual",
    )
    db_session.add_all([snap1, snap2])
    await db_session.commit()

    result = await db_session.execute(
        select(PatientLabHistory)
        .where(PatientLabHistory.patient_id == patient.id)
        .order_by(PatientLabHistory.recorded_at.desc())
    )
    rows = result.scalars().all()
    assert len(rows) == 2
    assert rows[0].lab_values["egfr"] == 55.0
    assert rows[1].lab_values["egfr"] == 60.0
