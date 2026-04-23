import pytest
import json
import uuid
from unittest.mock import AsyncMock, patch
from app.models.patient import PatientProfile, DiseaseFlags, LabValues


@pytest.mark.asyncio
async def test_analyze_endpoint_returns_200(client, db_session):
    patient = PatientProfile(
        patient_code="PT-API-001", age=65, gender="M",
        diseases=DiseaseFlags(hypertension=True).model_dump(),
        lab_values=LabValues(egfr=55.0).model_dump(),
        allergies=[],
    )
    db_session.add(patient)
    await db_session.commit()

    mock_response_json = json.dumps({
        "recommended_generics": [
            {
                "generic_name_ko": "암로디핀",
                "generic_name_en": "Amlodipine",
                "strength_mg": 5.0,
                "frequency": "QD",
                "rationale": "고혈압 1차 CCB",
                "guideline_reference": "ESC/ESH 2023",
                "risk_level": "low",
                "warnings": [],
            }
        ],
        "contraindicated_generics": [],
        "lab_delta_summary": "eGFR 안정적",
        "overall_risk": "low",
        "physician_action_required": False,
    })

    with patch("app.routers.inference.ClaudeProvider") as MockProvider:
        mock_instance = AsyncMock()
        mock_instance.complete.return_value = mock_response_json
        MockProvider.return_value = mock_instance

        res = await client.post(
            "/api/v1/inference/analyze",
            json={
                "patient_id": str(patient.id),
                "visit_date": "2026-04-23",
                "physician_note": "혈압 조절 필요",
            },
        )

    assert res.status_code == 200
    data = res.json()
    assert len(data["recommended_generics"]) == 1
    assert data["recommended_generics"][0]["generic_name_en"] == "Amlodipine"
    assert data["overall_risk"] == "low"


@pytest.mark.asyncio
async def test_analyze_endpoint_returns_404_for_unknown_patient(client):
    with patch("app.routers.inference.ClaudeProvider"):
        res = await client.post(
            "/api/v1/inference/analyze",
            json={
                "patient_id": str(uuid.uuid4()),
                "visit_date": "2026-04-23",
                "physician_note": "테스트",
            },
        )
    assert res.status_code == 404
