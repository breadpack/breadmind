"""Central event bus for BreadMind -- publish/subscribe pattern."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    # Agent lifecycle
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    INTENT_CLASSIFIED = "intent_classified"

    # Tool execution
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    TOOL_APPROVED = "tool_approved"
    TOOL_DENIED = "tool_denied"

    # Messenger
    MESSENGER_CONNECTED = "messenger_connected"
    MESSENGER_DISCONNECTED = "messenger_disconnected"
    MESSENGER_RECONNECTED = "messenger_reconnected"
    MESSENGER_FAILED = "messenger_failed"
    MESSENGER_ERROR = "messenger_error"

    # System
    PROVIDER_CHANGED = "provider_changed"
    CONFIG_UPDATED = "config_updated"
    MONITORING_ALERT = "monitoring_alert"

    # Memory
    MEMORY_SAVED = "memory_saved"
    MEMORY_PROMOTED = "memory_promoted"


@dataclass
class Event:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""  # e.g., "agent", "messenger.slack", "monitoring"


# Subscriber callback type
Subscriber = Callable[[Event], Awaitable[None]]


class EventBus:
    """Async publish/subscribe event bus. Thread-safe via asyncio."""

    def __init__(self) -> None:
        self._subscribers: dict[EventType | str, list[Subscriber]] = {}
        self._global_subscribers: list[Subscriber] = []

    def subscribe(self, event_type: EventType | str, callback: Subscriber) -> None:
        """Subscribe to a specific event type."""
        key = event_type
        if key not in self._subscribers:
            self._subscribers[key] = []
        self._subscribers[key].append(callback)

    def subscribe_all(self, callback: Subscriber) -> None:
        """Subscribe to ALL events (e.g., for logging or WebSocket broadcast)."""
        self._global_subscribers.append(callback)

    def unsubscribe(self, event_type: EventType | str, callback: Subscriber) -> None:
        """Remove a subscription."""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                s for s in self._subscribers[event_type] if s is not callback
            ]

    def unsubscribe_all(self, callback: Subscriber) -> None:
        """Remove a global subscription."""
        self._global_subscribers = [
            s for s in self._global_subscribers if s is not callback
        ]

    async def publish(self, event: Event) -> None:
        """Publish an event to all matching subscribers. Awaits all handlers."""
        # Type-specific subscribers
        for subscriber in self._subscribers.get(event.type, []):
            try:
                await subscriber(event)
            except Exception as e:
                logger.error("Event subscriber error for %s: %s", event.type, e)

        # Global subscribers
        for subscriber in self._global_subscribers:
            try:
                await subscriber(event)
            except Exception as e:
                logger.error("Global event subscriber error: %s", e)

    async def publish_fire_and_forget(self, event: Event) -> None:
        """Publish without waiting for subscribers (background task)."""
        asyncio.create_task(self.publish(event))


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Return the application-wide EventBus singleton."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
