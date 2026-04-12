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
        # Global subscribers — pass full Event object, not just data
        for handler in self._listeners.get("*", []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error("Global event handler error: %s", e)

    async def publish_fire_and_forget(self, event: "Event") -> None:
        asyncio.create_task(self.publish(event))

    # ── v3 Hook Chain API ──────────────────────────────────────────────
    def register_hook(self, event, handler, *, name: str | None = None) -> str:
        """Register a blocking-capable hook handler. Returns hook_id."""
        from breadmind.hooks.events import HookEvent

        key = event.value if isinstance(event, HookEvent) else str(event)
        if not hasattr(self, "_hook_chains"):
            self._hook_chains = {}
        import uuid
        hook_id = name or f"{key}:{handler.__class__.__name__}:{uuid.uuid4().hex[:8]}"
        handler_name = getattr(handler, "name", hook_id)
        if handler_name != hook_id and not name:
            hook_id = f"{key}:{handler_name}:{uuid.uuid4().hex[:6]}"
        chain = self._hook_chains.setdefault(key, [])
        chain.append((hook_id, handler))
        return hook_id

    def unregister_hook(self, hook_id: str) -> bool:
        if not hasattr(self, "_hook_chains"):
            return False
        for key, entries in self._hook_chains.items():
            for i, (hid, _handler) in enumerate(entries):
                if hid == hook_id:
                    entries.pop(i)
                    return True
        return False

    async def run_hook_chain(self, event, payload):
        """Run registered hooks for this event + dispatch listeners concurrently."""
        from breadmind.hooks.chain import HookChain
        from breadmind.hooks.decision import HookDecision
        from breadmind.hooks.events import HookEvent

        key = event.value if isinstance(event, HookEvent) else str(event)
        hook_chains = getattr(self, "_hook_chains", {})
        entries = hook_chains.get(key, [])

        # fire-and-forget listeners (observability)
        await self.async_emit(key, payload.data)

        if not entries:
            return HookDecision.proceed()

        try:
            hook_event = HookEvent(key)
        except ValueError:
            hook_event = HookEvent.NOTIFICATION

        chain = HookChain(
            event=hook_event,
            handlers=[h for _hid, h in entries],
        )
        decision, _payload = await chain.run(payload)
        return decision


# ── v1 Compatibility Types ─────────────────────────────────────────────

class EventType(str, Enum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    INTENT_CLASSIFIED = "intent_classified"
    ORCHESTRATOR_START = "orchestrator_start"
    ORCHESTRATOR_REPLAN = "orchestrator_replan"
    ORCHESTRATOR_END = "orchestrator_end"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_END = "subagent_end"
    DAG_BATCH_START = "dag_batch_start"
    DAG_BATCH_END = "dag_batch_end"
    MESSENGER_CONNECTED = "messenger_connected"
    MESSENGER_DISCONNECTED = "messenger_disconnected"
    MESSENGER_RECONNECTED = "messenger_reconnected"
    MESSENGER_FAILED = "messenger_failed"
    MCP_SERVER_ADDED = "mcp_server_added"
    MCP_SERVER_REMOVED = "mcp_server_removed"
    MCP_SERVER_ERROR = "mcp_server_error"
    MCP_TOOLS_UPDATED = "mcp_tools_updated"
    APPROVAL_REQUESTED = "approval_requested"
    SETTINGS_CHANGED = "settings_changed"
    PROGRESS = "progress"


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
