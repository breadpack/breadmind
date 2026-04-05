from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .token_counter import TokenCounter

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
class Attachment:
    """메시지 첨부 파일 (이미지, 파일 등)."""
    type: str  # "image", "file"
    path: str | None = None  # 로컬 파일 경로
    url: str | None = None   # URL
    data: str | None = None  # base64 encoded data
    media_type: str = ""     # "image/png", "image/jpeg", "application/pdf"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
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
    is_meta: bool = False
    attachments: list[Attachment] = field(default_factory=list)


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
        think_budget: int | None = None,
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

    async def close(self) -> None:
        """리소스를 정리한다. 서브클래스에서 필요시 override한다."""

    @property
    def model_name(self) -> str:
        """현재 사용 중인 모델 이름을 반환한다."""
        return "unknown"


class FallbackProvider(LLMProvider):
    """Wraps multiple providers with automatic failover."""

    def __init__(self, providers: list[LLMProvider]):
        self._providers = providers

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
        think_budget: int | None = None,
    ) -> LLMResponse:
        last_error: Exception | None = None
        for provider in self._providers:
            try:
                return await provider.chat(messages, tools, model, think_budget=think_budget)
            except Exception as e:
                last_error = e
                continue  # try next provider
        raise last_error  # type: ignore[misc]

    async def health_check(self) -> bool:
        for p in self._providers:
            if await p.health_check():
                return True
        return False


class ConversationSummarizer:
    """Summarize conversation when context gets too long."""

    def __init__(self, provider: LLMProvider, token_counter: TokenCounter):
        self._provider = provider
        self._token_counter = token_counter

    async def summarize_if_needed(
        self,
        messages: list[LLMMessage],
        model: str,
        threshold_ratio: float = 0.7,
    ) -> list[LLMMessage]:
        """If messages exceed threshold_ratio of context window, summarize older messages.

        Keep system prompt + last N messages, replace middle with summary.
        """
        total = self._token_counter.estimate_messages_tokens(messages)
        limit = self._token_counter.get_model_limit(model)

        if total < limit * threshold_ratio:
            return messages  # no summarization needed

        # Keep first system message and last 10 messages
        keep_last = min(10, len(messages) - 1)

        if len(messages) <= keep_last + 1:
            return messages  # not enough messages to summarize

        first_msg = messages[0] if messages[0].role == "system" else None
        start_idx = 1 if first_msg else 0
        to_summarize = messages[start_idx:-keep_last] if keep_last > 0 else messages[start_idx:]
        tail = messages[-keep_last:] if keep_last > 0 else []

        if not to_summarize:
            return messages

        # Build text from messages to summarize
        summary_parts = []
        for msg in to_summarize:
            if msg.content:
                summary_parts.append(f"{msg.role}: {msg.content}")

        summary_text = "\n".join(summary_parts)
        summary_prompt = (
            "Summarize this conversation concisely, keeping key decisions and facts:\n"
            + summary_text
        )
        summary_response = await self._provider.chat(
            [LLMMessage(role="user", content=summary_prompt)]
        )

        result: list[LLMMessage] = []
        if first_msg:
            result.append(first_msg)
        result.append(
            LLMMessage(
                role="system",
                content=f"Previous conversation summary: {summary_response.content}",
            )
        )
        result.extend(tail)
        return result
