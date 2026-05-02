import base64
import json
import re
import anthropic
from app.config import settings

_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 1024

_IMAGE_PROMPT = """이 이미지는 한국 의료기관의 혈액 검사 결과지입니다.
모든 검사 항목의 항목명(한글), 수치, 단위, 참고범위를 추출하여 아래 JSON 형식으로만 응답하세요.
다른 설명 없이 JSON만 출력하세요.

{
  "items": [
    {"name": "항목명", "value": 숫자_또는_null, "unit": "단위", "ref_range": "참고범위"}
  ]
}"""

_TEXT_PROMPT = """다음은 한국 의료기관의 검사 결과 텍스트입니다.
모든 검사 항목의 항목명(한글), 수치, 단위, 참고범위를 추출하여 아래 JSON 형식으로만 응답하세요.
다른 설명 없이 JSON만 출력하세요.

{
  "items": [
    {"name": "항목명", "value": 숫자_또는_null, "unit": "단위", "ref_range": "참고범위"}
  ]
}

검사 결과 텍스트:
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        text = match.group(1)
    return json.loads(text)


async def parse_image(image_bytes: bytes) -> dict:
    """이미지 바이트를 받아 검사 수치 목록을 반환한다."""
    b64 = base64.standard_b64encode(image_bytes).decode()
    message = await _client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
                },
                {"type": "text", "text": _IMAGE_PROMPT},
            ],
        }],
    )
    raw = message.content[0].text
    try:
        data = _extract_json(raw)
        return {"parsed": True, "items": data.get("items", []), "raw_text": raw}
    except (json.JSONDecodeError, KeyError, AttributeError):
        return {"parsed": False, "items": [], "raw_text": raw}


async def parse_text(raw_text: str) -> dict:
    """EMR 텍스트를 받아 검사 수치 목록을 반환한다."""
    message = await _client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": _TEXT_PROMPT + raw_text}],
    )
    raw = message.content[0].text
    try:
        data = _extract_json(raw)
        return {"parsed": True, "items": data.get("items", []), "raw_text": raw}
    except (json.JSONDecodeError, KeyError, AttributeError):
        return {"parsed": False, "items": [], "raw_text": raw}
