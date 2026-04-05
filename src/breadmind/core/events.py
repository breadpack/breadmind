"""Central event bus for BreadMind — v2 string-based + v1 compatibility layer."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


# ── v2 Core EventBus ──────────────────────────────────────────────────

class EventBus:
    """v2 타입드 이벤트 버스 + v1 호환."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable]] = defaultdict(list)

    # v2 API
    def on(self, event: str, handler: Callable) -> None:
        self._listeners[event].append(handler)

    def off(self, event: str, handler: Callable) -> None:
        listeners = self._listeners.get(event, [])
        if handler in listeners:
            listeners.remove(handler)

    def emit(self, event: str, data: Any = None) -> None:
        for handler in self._listeners.get(event, []):
            if asyncio.iscoroutinefunction(handler):
                continue
            handler(data)

    async def async_emit(self, event: str, data: Any = None) -> None:
        for handler in self._listeners.get(event, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as e:
                logger.error("Event handler error for %s: %s", event, e)

    # v1 compatibility API
    def subscribe(self, event_type: "EventType | str", callback: Callable) -> None:
        key = event_type.value if isinstance(event_type, EventType) else event_type
        self.on(key, callback)

    def subscribe_all(self, callback: Callable) -> None:
        self.on("*", callback)

    def unsubscribe(self, event_type: "EventType | str", callback: Callable) -> None:
        key = event_type.value if isinstance(event_type, EventType) else event_type
        self.off(key, callback)

    def unsubscribe_all(self, callback: Callable) -> None:
        self.off("*", callback)

    async def publish(self, event: "Event") -> None:
        key = event.type.value if isinstance(event.type, EventType) else str(event.type)
        await self.async_emit(key, event.data)
        # Global subscribers
        for handler in self._listeners.get("*", []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event.data)
                else:
                    handler(event.data)
            except Exception as e:
                logger.error("Global event handler error: %s", e)

    async def publish_fire_and_forget(self, event: "Event") -> None:
        asyncio.create_task(self.publish(event))


# ── v1 Compatibility Types ─────────────────────────────────────────────

class EventType(str, Enum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    INTENT_CLASSIFIED = "intent_classified"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    TOOL_APPROVED = "tool_approved"
    TOOL_DENIED = "tool_denied"
    ORCHESTRATOR_START = "orchestrator_start"
    ORCHESTRATOR_REPLAN = "orchestrator_replan"
    ORCHESTRATOR_END = "orchestrator_end"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_END = "subagent_end"
    SUBAGENT_FAILED = "subagent_failed"
    DAG_BATCH_START = "dag_batch_start"
    DAG_BATCH_END = "dag_batch_end"
    MESSENGER_CONNECTED = "messenger_connected"
    MESSENGER_DISCONNECTED = "messenger_disconnected"
    MESSENGER_RECONNECTED = "messenger_reconnected"
    MESSENGER_FAILED = "messenger_failed"
    MESSENGER_ERROR = "messenger_error"
    PROVIDER_CHANGED = "provider_changed"
    CONFIG_UPDATED = "config_updated"
    MONITORING_ALERT = "monitoring_alert"
    MEMORY_SAVED = "memory_saved"
    MEMORY_PROMOTED = "memory_promoted"
    MCP_SERVER_ADDED = "mcp_server_added"
    MCP_SERVER_REMOVED = "mcp_server_removed"
    MCP_SERVER_ERROR = "mcp_server_error"
    MCP_TOOLS_UPDATED = "mcp_tools_updated"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    # Lifecycle events (Round 11)
    STOP = "stop"
    SUBAGENT_STOP = "subagent_stop"
    PRE_COMPACT = "pre_compact"
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    PERMISSION_REQUEST = "permission_request"
    # Extended lifecycle events
    INSTRUCTIONS_LOADED = "instructions_loaded"
    POST_TOOL_USE_FAILURE = "post_tool_use_failure"
    STOP_FAILURE = "stop_failure"
    SUBAGENT_START_HOOK = "subagent_start_hook"
    TASK_CREATED = "task_created"
    TASK_COMPLETED = "task_completed"
    TEAMMATE_IDLE = "teammate_idle"
    CONFIG_CHANGE = "config_change"
    CWD_CHANGED = "cwd_changed"
    FILE_CHANGED = "file_changed"
    POST_COMPACT = "post_compact"
    WORKTREE_CREATE = "worktree_create"
    WORKTREE_REMOVE = "worktree_remove"
    NOTIFICATION = "notification"
    ELICITATION = "elicitation"


@dataclass
class Event:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""


# ── Singleton ──────────────────────────────────────────────────────────

_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
