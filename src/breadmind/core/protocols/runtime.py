from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class UserInput:
    """런타임에서 수신한 사용자 입력."""
    text: str
    user: str = "anonymous"
    channel: str = "default"
    session_id: str = ""
    attachments: list[str] = field(default_factory=list)


@dataclass
class AgentOutput:
    """에이전트가 런타임에 전송하는 출력."""
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Progress:
    """진행 상황 알림."""
    status: str
    detail: str = ""


@runtime_checkable
class RuntimeProtocol(Protocol):
    """실행 환경 추상화 계약."""
    async def start(self, container: Any) -> None: ...
    async def stop(self) -> None: ...
    async def receive(self) -> UserInput: ...
    async def send(self, output: AgentOutput) -> None: ...
    async def send_progress(self, progress: Progress) -> None: ...
