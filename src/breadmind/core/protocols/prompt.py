from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol
from breadmind.core.protocols.provider import Message


@dataclass
class PromptBlock:
    """시스템 프롬프트의 단위 블록."""
    section: str
    content: str
    cacheable: bool = False
    priority: int = 5
    provider_hints: dict[str, Any] = field(default_factory=dict)


@dataclass
class PromptContext:
    """프롬프트 빌드에 필요한 런타임 컨텍스트."""
    persona_name: str = "BreadMind"
    language: str = "ko"
    specialties: list[str] = field(default_factory=list)
    os_info: str = ""
    current_date: str = ""
    available_tools: list[str] = field(default_factory=list)
    provider_model: str = ""
    custom_instructions: str | None = None
    role: str | None = None
    persona: str = "professional"


@dataclass
class CompactResult:
    """컨텍스트 압축 결과."""
    boundary: Message
    preserved: list[Message]
    tokens_saved: int


class PromptProtocol(Protocol):
    """프롬프트 빌드/캐시/압축 계약."""
    def build(self, context: PromptContext) -> list[PromptBlock]: ...
    def rebuild_dynamic(self, context: PromptContext) -> list[PromptBlock]: ...
    async def compact(self, messages: list[Message], budget_tokens: int) -> CompactResult: ...
    def inject_reminder(self, key: str, content: str) -> Message: ...
