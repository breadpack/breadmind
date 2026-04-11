"""Approval flow for safety-gated tool calls."""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Protocol

from breadmind.core.events import EventBus
from breadmind.utils.serialization import SerializableMixin

logger = logging.getLogger(__name__)


@dataclass
class ApprovalRequest(SerializableMixin):
    """승인 요청 데이터."""
    request_id: str
    tool_name: str
    arguments: dict[str, Any]
    reason: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def create(tool_name: str, arguments: dict[str, Any], reason: str) -> ApprovalRequest:
        return ApprovalRequest(
            request_id=uuid.uuid4().hex,
            tool_name=tool_name,
            arguments=arguments,
            reason=reason,
        )


@dataclass
class ApprovalResponse(SerializableMixin):
    """승인 응답 데이터."""
    request_id: str
    approved: bool
    modified_arguments: dict[str, Any] | None = None


class ApprovalHandler(Protocol):
    """승인 요청을 처리하는 인터페이스."""
    async def request_approval(self, request: ApprovalRequest) -> ApprovalResponse: ...


class AutoApproveHandler:
    """auto 모드: 모든 요청 자동 승인."""

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResponse:
        return ApprovalResponse(request_id=request.request_id, approved=True)


class AutoDenyHandler:
    """모든 요청 자동 거부."""

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResponse:
        return ApprovalResponse(request_id=request.request_id, approved=False)


class CallbackApprovalHandler:
    """콜백 함수 기반 승인 처리."""

    def __init__(self, callback: Callable[[ApprovalRequest], Awaitable[ApprovalResponse]]) -> None:
        self._callback = callback

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResponse:
        return await self._callback(request)


class EventBusApprovalHandler:
    """EventBus를 통한 비동기 승인. 외부(CLI/WebSocket)에서 응답을 받을 때까지 대기."""

    def __init__(self, event_bus: EventBus, timeout: float = 60.0) -> None:
        self._event_bus = event_bus
        self._timeout = timeout
        self._pending: dict[str, asyncio.Future[ApprovalResponse]] = {}

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResponse:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ApprovalResponse] = loop.create_future()
        self._pending[request.request_id] = future

        await self._event_bus.async_emit("approval_requested", request.to_dict())

        try:
            return await asyncio.wait_for(future, self._timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "Approval request %s timed out after %.1fs — auto-denied",
                request.request_id, self._timeout,
            )
            return ApprovalResponse(request_id=request.request_id, approved=False)
        finally:
            self._pending.pop(request.request_id, None)

    def resolve(self, request_id: str, approved: bool,
                modified_arguments: dict[str, Any] | None = None) -> None:
        """외부에서 호출하여 승인/거부 응답 전달. Thread-safe."""
        future = self._pending.get(request_id)
        if future is None:
            logger.warning("No pending approval request: %s", request_id)
            return
        if future.done():
            logger.warning("Approval request already resolved: %s", request_id)
            return

        response = ApprovalResponse(
            request_id=request_id,
            approved=approved,
            modified_arguments=modified_arguments,
        )
        # thread-safe: call_soon_threadsafe for cross-thread resolve
        loop = future.get_loop()
        loop.call_soon_threadsafe(future.set_result, response)

    @property
    def pending_count(self) -> int:
        return len(self._pending)
