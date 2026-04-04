from __future__ import annotations
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolCallRequest:
    """LLM이 요청한 도구 호출."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class TokenUsage:
    """토큰 사용량."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )


@dataclass
class Attachment:
    """메시지 첨부 파일 (이미지, 파일 등)."""
    type: str  # "image", "file"
    path: str | None = None  # 로컬 파일 경로
    url: str | None = None   # URL
    data: str | None = None  # base64 encoded data
    media_type: str = ""     # "image/png", "image/jpeg", "application/pdf"


@dataclass
class Message:
    """대화 메시지."""
    role: str
    content: str | None = None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None
    is_meta: bool = False
    attachments: list[Attachment] = field(default_factory=list)


@dataclass
class LLMResponse:
    """LLM 응답."""
    content: str | None
    tool_calls: list[ToolCallRequest]
    usage: TokenUsage
    stop_reason: str

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class CacheStrategy:
    """프로바이더별 캐시 전략."""
    name: str
    config: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
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
