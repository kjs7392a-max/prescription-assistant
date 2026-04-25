from typing import AsyncIterator
import anthropic
from app.services.llm.base import BaseLLMProvider
from app.config import settings

MODEL = "claude-sonnet-4-6"            # 사용자 지정 — 답변은 짧게 강제
MAX_TOKENS = 3500                      # 표준 6필드 + recommendation_set + 안전 여유


def _system_with_cache(system: str) -> list[dict]:
    """system 프롬프트에 ephemeral cache_control 적용 — 두 번째 호출부터 즉시 재사용."""
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


class ClaudeProvider(BaseLLMProvider):
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def complete(self, system: str, user: str) -> str:
        message = await self._client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_system_with_cache(system),
            messages=[{"role": "user", "content": user}],
        )
        if message.stop_reason == "max_tokens":
            raise RuntimeError(
                f"LLM 응답이 max_tokens({MAX_TOKENS})에 도달하여 잘렸습니다."
            )
        return message.content[0].text

    async def stream_complete(self, system: str, user: str) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_system_with_cache(system),
            messages=[{"role": "user", "content": user}],
        ) as stream:
            async for text in stream.text_stream:
                yield text
