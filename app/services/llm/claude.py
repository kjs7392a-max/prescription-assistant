import anthropic
from app.services.llm.base import BaseLLMProvider
from app.config import settings

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2048


class ClaudeProvider(BaseLLMProvider):
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def complete(self, system: str, user: str) -> str:
        message = await self._client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return message.content[0].text
