import pytest
from unittest.mock import AsyncMock, MagicMock, patch

MOCK_JSON = '{"items": [{"name": "혈당", "value": 105.0, "unit": "mg/dL", "ref_range": "70-100"}]}'


@pytest.mark.asyncio
async def test_parse_image_success():
    mock_content = MagicMock()
    mock_content.text = MOCK_JSON
    mock_msg = MagicMock()
    mock_msg.content = [mock_content]
    mock_msg.stop_reason = "end_turn"

    with patch("app.services.lab_ocr._client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=mock_msg)
        from app.services.lab_ocr import parse_image
        result = await parse_image(b"fake_image_bytes")

    assert result["parsed"] is True
    assert len(result["items"]) == 1
    assert result["items"][0]["name"] == "혈당"
    assert result["items"][0]["value"] == 105.0


@pytest.mark.asyncio
async def test_parse_text_success():
    mock_content = MagicMock()
    mock_content.text = MOCK_JSON
    mock_msg = MagicMock()
    mock_msg.content = [mock_content]
    mock_msg.stop_reason = "end_turn"

    with patch("app.services.lab_ocr._client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=mock_msg)
        from app.services.lab_ocr import parse_text
        result = await parse_text("혈당: 105 mg/dL (참고범위: 70-100)")

    assert result["parsed"] is True
    assert result["items"][0]["name"] == "혈당"


@pytest.mark.asyncio
async def test_parse_image_handles_invalid_json():
    mock_content = MagicMock()
    mock_content.text = "죄송합니다, 이미지를 인식할 수 없습니다."
    mock_msg = MagicMock()
    mock_msg.content = [mock_content]
    mock_msg.stop_reason = "end_turn"

    with patch("app.services.lab_ocr._client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=mock_msg)
        from app.services.lab_ocr import parse_image
        result = await parse_image(b"blurry_image")

    assert result["parsed"] is False
    assert result["items"] == []
