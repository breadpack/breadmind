from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolDefinition:
    """도구 정의."""
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolSchema:
    """LLM에 전달되는 도구 스키마."""
    name: str
    deferred: bool = False
    definition: ToolDefinition | None = None


@dataclass
class ToolCall:
    """에이전트 루프에서 실행할 도구 호출."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """도구 실행 결과."""
    success: bool
    output: str
    error: str | None = None


@dataclass
class ToolFilter:
    """도구 필터링 조건."""
    intent: str | None = None
    keywords: list[str] = field(default_factory=list)
    always_include: list[str] = field(default_factory=list)
    max_tools: int | None = None
    use_deferred: bool = False


@dataclass
class ExecutionContext:
    """도구 실행 시 전달되는 컨텍스트."""
    user: str = ""
    channel: str = ""
    session_id: str = ""
    autonomy: str = "confirm-destructive"


@runtime_checkable
class ToolProtocol(Protocol):
    """도구 등록/실행/검색 계약."""
    def register(self, tool: ToolDefinition) -> None: ...
    def unregister(self, name: str) -> None: ...
    def get_schemas(self, filter: ToolFilter | None = None) -> list[ToolSchema]: ...
    async def execute(self, call: ToolCall, ctx: ExecutionContext) -> ToolResult: ...
    def get_deferred_tools(self) -> list[str]: ...
    def resolve_deferred(self, names: list[str]) -> list[ToolSchema]: ...
