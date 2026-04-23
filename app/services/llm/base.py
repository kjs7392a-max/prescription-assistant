from abc import ABC, abstractmethod


class BaseLLMProvider(ABC):
    """LLM 공급자 추상 인터페이스 — ClaudeProvider 등이 구현"""

    @abstractmethod
    async def complete(self, system: str, user: str) -> str:
        """system 프롬프트와 user 메시지를 받아 LLM 응답 텍스트를 반환"""
        ...
