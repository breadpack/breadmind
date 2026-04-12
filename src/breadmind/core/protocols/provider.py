from __future__ import annotations
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Protocol

from breadmind.llm.base import (
    Attachment,  # noqa: F401
    LLMMessage as Message,
    LLMResponse,
    TokenUsage,  # noqa: F401
    ToolCall,
)

# Backward compatibility alias
ToolCallRequest = ToolCall


@dataclass
class CacheStrategy:
    """프로바이더별 캐시 전략."""
    name: str
    config: dict[str, Any] = field(default_factory=dict)


class ProviderProtocol(Protocol):
    """LLM 프로바이더 계약."""
    async def chat(
        self, messages: list[Message], tools: list[Any] | None = None,
        think_budget: int | None = None,
    ) -> LLMResponse: ...

    async def chat_stream(
        self, messages: list[Message], tools: list[Any] | None = None,
    ) -> AsyncGenerator[str, None]:
        """스트리밍 응답을 반환한다. 기본 구현은 chat()으로 폴백."""
        response = await self.chat(messages, tools)
        if response.content:
            yield response.content

    def get_cache_strategy(self) -> CacheStrategy | None:
        return None

    def supports_feature(self, feature: str) -> bool:
        return False

    def transform_system_prompt(self, blocks: list[Any]) -> Any:
        return blocks

    def transform_messages(self, messages: list[Message]) -> list[Any]:
        return messages

    @property
    def fallback(self) -> ProviderProtocol | None:
        return None
