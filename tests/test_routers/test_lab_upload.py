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
