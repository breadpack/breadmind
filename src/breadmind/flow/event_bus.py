"""FlowEventBus: in-process fan-out + optional Redis backplane."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator
from uuid import UUID

from breadmind.flow.events import FlowEvent
from breadmind.flow.store import FlowEventStore

logger = logging.getLogger(__name__)


class _Subscription:
    def __init__(
        self,
        subscriber_id: str,
        flow_id: UUID | None,
        user_id: str | None,
        event_types: set[str] | None,
    ) -> None:
        self.subscriber_id = subscriber_id
        self.flow_id = flow_id
        self.user_id = user_id
        self.event_types = event_types
        self.queue: asyncio.Queue[FlowEvent] = asyncio.Queue(maxsize=1000)

    def matches(self, event: FlowEvent) -> bool:
        if self.flow_id is not None and event.flow_id != self.flow_id:
            return False
        if self.event_types is not None and event.event_type.value not in self.event_types:
            return False
        if self.user_id is not None:
            payload_user = event.payload.get("user_id")
            if payload_user is not None and payload_user != self.user_id:
                return False
        return True


class FlowEventBus:
    def __init__(self, store: FlowEventStore, redis: Any | None = None) -> None:
        self._store = store
        self._redis = redis
        self._subscriptions: dict[str, _Subscription] = {}
        self._redis_pubsub_task: asyncio.Task | None = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        if self._redis is not None:
            self._redis_pubsub_task = asyncio.create_task(self._redis_listener())
        self._started = True

    async def stop(self) -> None:
        if self._redis_pubsub_task:
            self._redis_pubsub_task.cancel()
            try:
                await self._redis_pubsub_task
            except asyncio.CancelledError:
                pass
        self._started = False

    async def publish(self, event: FlowEvent) -> FlowEvent:
        stored = await self._store.append(event)
        self._dispatch_local(stored)
        if self._redis is not None:
            try:
                await self._redis.publish(
                    f"flow_events:{stored.flow_id}",
                    json.dumps(stored.to_dict()),
                )
            except Exception as exc:
                logger.warning("redis publish failed: %s", exc)
        return stored

    def _dispatch_local(self, event: FlowEvent) -> None:
        dead: list[str] = []
        for sid, sub in self._subscriptions.items():
            if not sub.matches(event):
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("subscriber %s queue full, dropping", sid)
                dead.append(sid)
        for sid in dead:
            self._subscriptions.pop(sid, None)

    async def subscribe(
        self,
        subscriber_id: str,
        *,
        flow_id: UUID | None = None,
        user_id: str | None = None,
        event_types: set[str] | None = None,
    ) -> AsyncIterator[FlowEvent]:
        sub = _Subscription(subscriber_id, flow_id, user_id, event_types)
        self._subscriptions[subscriber_id] = sub
        try:
            while True:
                ev = await sub.queue.get()
                yield ev
        finally:
            self._subscriptions.pop(subscriber_id, None)

    async def replay(self, flow_id: UUID, from_seq: int = 0) -> list[FlowEvent]:
        return await self._store.replay(flow_id, from_seq)

    async def _redis_listener(self) -> None:
        try:
            pubsub = self._redis.pubsub()
            await pubsub.psubscribe("flow_events:*")
            async for msg in pubsub.listen():
                if msg.get("type") not in ("pmessage", "message"):
                    continue
                try:
                    data = json.loads(msg["data"])
                    event = FlowEvent.from_dict(data)
                    self._dispatch_local(event)
                except Exception as exc:
                    logger.warning("redis msg parse failed: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("redis listener crashed: %s", exc)
