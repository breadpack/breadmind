from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

# 모델별 가격 정보 (USD per 1M tokens)
_MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_creation": 3.75,
        "cache_read": 0.30,
    },
    "claude-haiku-4-5": {
        "input": 0.80,
        "output": 4.0,
        "cache_creation": 1.0,
        "cache_read": 0.08,
    },
}


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """모든 토큰 수의 합계를 반환한다."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )

    def cost(self, model: str) -> float:
        """주어진 모델의 가격 정보를 기반으로 비용(USD)을 계산한다."""
        pricing = _MODEL_PRICING.get(model)
        if pricing is None:
            raise ValueError(f"지원되지 않는 모델: {model}")

        per_million = 1_000_000.0
        return (
            self.input_tokens * pricing["input"] / per_million
            + self.output_tokens * pricing["output"] / per_million
            + self.cache_creation_input_tokens * pricing["cache_creation"] / per_million
            + self.cache_read_input_tokens * pricing["cache_read"] / per_million
        )


@dataclass
class LLMMessage:
    role: str  # "user" | "assistant" | "system" | "tool"
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    usage: TokenUsage
    stop_reason: str

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        ...

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """스트리밍 응답을 반환한다. 기본 구현은 chat()으로 폴백하여 전체 응답을 한 번에 반환한다."""
        response = await self.chat(messages, tools, model)
        if response.content:
            yield response.content

    @abstractmethod
    async def health_check(self) -> bool:
        ...
