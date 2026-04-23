import pytest
import json
import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock
from app.models.patient import PatientProfile, DiseaseFlags, LabValues
from app.models.lab_history import PatientLabHistory
from app.models.feedback import PrescriptionFeedback
from app.models.drug import DrugKnowledgeBase
from app.models.prescription import PrescriptionLog
from app.schemas.inference import InferenceRequest
from app.services.inference import InferenceEngine


def _make_llm_response(**kwargs) -> str:
    default = {
        "recommended_generics": [
            {
                "generic_name_ko": "암로디핀",
                "generic_name_en": "Amlodipine",
                "strength_mg": 5.0,
                "frequency": "QD",
                "rationale": "고혈압 1차 선택 CCB",
                "guideline_reference": "ESC/ESH 2023",
                "risk_level": "low",
                "warnings": ["부종 모니터링"],
            }
        ],
        "contraindicated_generics": [],
        "lab_delta_summary": "eGFR 안정적",
        "overall_risk": "low",
        "physician_action_required": False,
    }
    default.update(kwargs)
    return json.dumps(default)


@pytest.mark.asyncio
async def test_inference_returns_structured_response(db_session):
    patient = PatientProfile(
        patient_code="PT-INF-001", age=65, gender="M",
        diseases=DiseaseFlags(hypertension=True).model_dump(),
        lab_values=LabValues(egfr=55.0).model_dump(),
        allergies=[],
    )
    db_session.add(patient)
    await db_session.flush()

    mock_llm = AsyncMock()
    mock_llm.complete.return_value = _make_llm_response()

    engine = InferenceEngine(llm=mock_llm)
    request = InferenceRequest(
        patient_id=patient.id,
        visit_date=date.today(),
        physician_note="혈압 조절 필요",
    )
    response = await engine.analyze(db_session, request)

    assert len(response.recommended_generics) == 1
    assert response.recommended_generics[0].generic_name_en == "Amlodipine"
    assert response.overall_risk == "low"
    assert mock_llm.complete.called


@pytest.mark.asyncio
async def test_inference_includes_adverse_event_in_prompt(db_session):
    patient = PatientProfile(
        patient_code="PT-INF-002", age=70, gender="F",
        diseases=DiseaseFlags(hypertension=True).model_dump(),
        lab_values=LabValues().model_dump(),
        allergies=[],
    )
    drug = DrugKnowledgeBase(
        generic_name_ko="에날라프릴", generic_name_en="Enalapril",
        drug_class="ACE inhibitor", indications=["고혈압"],
        contraindications={"absolute": [], "relative": []},
        standard_dosage={"initial": {"dose_mg": 5, "frequency": "BID", "route": "PO"}, "max_daily_mg": 40},
        dose_forms=["tablet"], strengths_available_mg=[5],
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
        clinical_rationale="고혈압",
        warnings=[],
    )
    db_session.add(log)
    await db_session.flush()

    feedback = PrescriptionFeedback(
        prescription_log_id=log.id, patient_id=patient.id,
        feedback_type="adverse_event", severity="severe",
        description="혈관부종", affected_generic_ko="에날라프릴",
        affected_generic_en="Enalapril", recorded_by="Dr.Kim",
    )
    db_session.add(feedback)
    await db_session.commit()

    mock_llm = AsyncMock()
    mock_llm.complete.return_value = _make_llm_response()

    engine = InferenceEngine(llm=mock_llm)
    request = InferenceRequest(
        patient_id=patient.id,
        visit_date=date.today(),
        physician_note="혈압 재평가",
    )
    await engine.analyze(db_session, request)

    call_args = mock_llm.complete.call_args
    user_prompt = call_args.kwargs.get("user") or call_args.args[1]
    assert "Enalapril" in user_prompt
    assert "혈관부종" in user_prompt


@pytest.mark.asyncio
async def test_inference_includes_lab_delta_in_prompt(db_session):
    patient = PatientProfile(
        patient_code="PT-INF-003", age=60, gender="M",
        diseases=DiseaseFlags(ckd=True).model_dump(),
        lab_values=LabValues(egfr=60.0).model_dump(),
        allergies=[],
    )
    db_session.add(patient)
    await db_session.flush()

    db_session.add(PatientLabHistory(
        patient_id=patient.id,
        recorded_at=datetime(2026, 2, 1),
        lab_values={"egfr": 60.0},
        source="manual",
    ))
    db_session.add(PatientLabHistory(
        patient_id=patient.id,
        recorded_at=datetime(2026, 3, 1),
        lab_values={"egfr": 45.0},
        source="manual",
    ))
    await db_session.commit()

    mock_llm = AsyncMock()
    mock_llm.complete.return_value = _make_llm_response(
        lab_delta_summary="eGFR: 60→45→40, 급격한 하강"
    )

    engine = InferenceEngine(llm=mock_llm)
    request = InferenceRequest(
        patient_id=patient.id,
        visit_date=date.today(),
        current_lab_values=LabValues(egfr=40.0),
        physician_note="신기능 악화 우려",
    )
    response = await engine.analyze(db_session, request)

    call_args = mock_llm.complete.call_args
    user_prompt = call_args.kwargs.get("user") or call_args.args[1]
    assert "40" in user_prompt
    assert response.lab_delta_summary == "eGFR: 60→45→40, 급격한 하강"
