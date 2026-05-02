import pytest
from unittest.mock import AsyncMock, patch

MOCK_OCR = {
    "parsed": True,
    "items": [{"name": "혈당", "value": 105.0, "unit": "mg/dL", "ref_range": "70-100"}],
    "raw_text": '{"items": [...]}',
}


@pytest.mark.asyncio
async def test_photo_upload_returns_pending(client):
    with patch("app.routers.lab_upload.parse_image", AsyncMock(return_value=MOCK_OCR)):
        response = await client.post(
            "/api/v1/lab-upload/photo",
            files={"photo": ("test.jpg", b"fake_jpeg_bytes", "image/jpeg")},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "pending"
    assert "id" in data
    assert data["is_parsed"] is True


@pytest.mark.asyncio
async def test_get_pending_list(client):
    with patch("app.routers.lab_upload.parse_image", AsyncMock(return_value=MOCK_OCR)):
        await client.post(
            "/api/v1/lab-upload/photo",
            files={"photo": ("test.jpg", b"fake_jpeg_bytes", "image/jpeg")},
        )
    response = await client.get("/api/v1/lab-upload/pending")
    assert response.status_code == 200
    assert len(response.json()) >= 1


@pytest.mark.asyncio
async def test_text_parse_returns_items(client):
    with patch("app.routers.lab_upload.parse_text", AsyncMock(return_value=MOCK_OCR)):
        response = await client.post(
            "/api/v1/lab-upload/text",
            json={"raw_text": "혈당: 105 mg/dL"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["parsed"] is True
    assert data["items"][0]["name"] == "혈당"


@pytest.mark.asyncio
async def test_confirm_submission(client, db_session):
    from app.models.patient import PatientProfile, DiseaseFlags, LabValues
    # Create a real patient
    patient = PatientProfile(
        patient_code="TEST-CONFIRM-001",
        age=50,
        gender="M",
        diseases=DiseaseFlags().model_dump(),
        lab_values=LabValues().model_dump(),
        allergies=[],
    )
    db_session.add(patient)
    await db_session.commit()

    # Create a pending submission
    with patch("app.routers.lab_upload.parse_image", AsyncMock(return_value=MOCK_OCR)):
        upload_res = await client.post(
            "/api/v1/lab-upload/photo",
            files={"photo": ("test.jpg", b"fake_jpeg_bytes", "image/jpeg")},
        )
    submission_id = upload_res.json()["id"]

    # Confirm it
    from datetime import datetime
    confirm_res = await client.patch(
        f"/api/v1/lab-upload/{submission_id}/confirm",
        json={
            "patient_code": "TEST-CONFIRM-001",
            "lab_values": {"혈당": 105.0},
            "recorded_at": datetime.utcnow().isoformat(),
        },
    )
    assert confirm_res.status_code == 200
    data = confirm_res.json()
    assert data["status"] == "saved"
    assert data["patient_id"] is not None

    # Double confirm should 409
    confirm_res2 = await client.patch(
        f"/api/v1/lab-upload/{submission_id}/confirm",
        json={
            "patient_code": "TEST-CONFIRM-001",
            "lab_values": {"혈당": 105.0},
            "recorded_at": datetime.utcnow().isoformat(),
        },
    )
    assert confirm_res2.status_code == 409
