from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol


@dataclass
class AgentContext:
    """에이전트 실행 컨텍스트."""
    user: str
    channel: str
    session_id: str
    parent_agent: str | None = None
    depth: int = 0
    max_depth: int = 5
    isolation: str | None = None
    resume: bool = False


@dataclass
class AgentResponse:
    """에이전트 응답."""
    content: str
    tool_calls_count: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0


class AgentProtocol(Protocol):
    """에이전트 생명주기 계약."""
    @property
    def agent_id(self) -> str: ...
    async def handle_message(self, message: str, ctx: AgentContext) -> AgentResponse: ...
    async def spawn(self, prompt: str, tools: list[str] | None = None, isolation: str | None = None) -> AgentProtocol: ...
    async def send_message(self, target: str, message: str) -> str: ...
    def set_role(self, role: str) -> None: ...
