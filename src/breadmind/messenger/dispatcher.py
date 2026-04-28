"""Outbox -> Redis publish dispatcher.

Polls `message_outbox` rows, publishes a JSON envelope to
`channel:<channel_id>.events`, and deletes the published row. At-most-once
delivery — clients can recover missed events via the relay's BackfillSince
request (M2c). Closes M2a dep #8.

This module exposes the building blocks; the actual lifespan-bound
``OutboxDispatcher.run()`` task start is M2b's responsibility (it touches
FastAPI startup ordering and Redis client construction).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class _Publisher(Protocol):
    async def publish(self, channel: str, payload: str | bytes) -> int: ...


async def dispatch_one_batch(db, redis: _Publisher, *, batch_size: int = 100) -> int:
    """Publish up to ``batch_size`` outbox rows. Returns count published.

    Order: oldest rows first (FIFO via ``created_at ASC``). Failures on
    individual rows are logged and skipped; their rows remain in the outbox
    and will be retried on the next batch.
    """
    rows = await db.fetch(
        "SELECT id, channel_id, event_type, payload "
        "FROM message_outbox "
        "ORDER BY created_at ASC "
        "LIMIT $1",
        batch_size,
    )
    if not rows:
        return 0

    published_ids = []
    for row in rows:
        raw_payload = row["payload"]
        envelope = {
            "type": row["event_type"],
            "payload": json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload,
        }
        channel = f"channel:{row['channel_id']}.events"
        try:
            await redis.publish(channel, json.dumps(envelope))
        except Exception as e:  # noqa: BLE001
            logger.warning("outbox publish failed id=%s: %s", row["id"], e)
            continue
        published_ids.append(row["id"])

    if published_ids:
        await db.execute(
            "DELETE FROM message_outbox WHERE id = ANY($1::uuid[])",
            published_ids,
        )
    return len(published_ids)


class OutboxDispatcher:
    """Long-running poll loop. Cancel the asyncio.Task to stop.

    When the outbox is empty, sleeps ``poll_interval`` seconds before the
    next probe. When the batch is fully drained (``batch_size`` rows
    returned), immediately polls again to catch up under load.
    """

    def __init__(
        self,
        db,
        redis: _Publisher,
        *,
        poll_interval: float = 0.5,
        batch_size: int = 100,
    ):
        self._db = db
        self._redis = redis
        self._poll_interval = poll_interval
        self._batch_size = batch_size

    async def run(self) -> None:
        while True:
            try:
                n = await dispatch_one_batch(
                    self._db, self._redis, batch_size=self._batch_size
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.exception("dispatcher batch failed: %s", e)
                n = 0
            if n == 0:
                await asyncio.sleep(self._poll_interval)
