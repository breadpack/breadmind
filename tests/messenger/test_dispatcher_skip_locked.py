"""Two concurrent dispatchers must not both publish the same outbox row.

Validates that ``dispatch_one_batch`` uses ``SELECT ... FOR UPDATE SKIP LOCKED``
so multiple workers consume disjoint row sets even when racing on the same
table.

Marked ``relay_integration`` because it requires a live PostgreSQL connection
to exercise the row-level locking semantics — fakeasyncpg / mocks cannot
reproduce SKIP LOCKED behavior.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from breadmind.messenger.dispatcher import dispatch_one_batch


class _CountingPublisher:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self._lock = asyncio.Lock()

    async def publish(self, channel: str, payload: str | bytes) -> int:
        async with self._lock:
            self.calls.append(
                (channel, payload if isinstance(payload, str) else payload.decode())
            )
        return 1


@pytest.mark.relay_integration
async def test_concurrent_dispatchers_publish_each_row_exactly_once(
    test_db, seed_channel
):
    """Insert 50 outbox rows; run 4 dispatchers in parallel; assert 50 publishes."""
    wid, channel_id, _owner_id = seed_channel
    expires = datetime.now(timezone.utc) + timedelta(seconds=300)

    # Isolate from any leftover rows
    await test_db.execute("DELETE FROM message_outbox")

    async with test_db.acquire() as conn:
        for i in range(50):
            await conn.execute(
                "INSERT INTO message_outbox "
                "(id, workspace_id, channel_id, event_type, payload, expires_at) "
                "VALUES ($1, $2, $3, 'message_created', $4::jsonb, $5)",
                uuid4(), wid, channel_id, json.dumps({"i": i}), expires,
            )

    pub = _CountingPublisher()

    async def worker():
        async with test_db.acquire() as conn:
            return await dispatch_one_batch(conn, pub, batch_size=20)

    counts = await asyncio.gather(worker(), worker(), worker(), worker())
    total = sum(counts)
    assert total == 50, f"expected exactly 50 publishes, got {total}"
    assert len(pub.calls) == 50

    remaining = await test_db.fetchval(
        "SELECT count(*) FROM message_outbox WHERE channel_id = $1", channel_id
    )
    assert remaining == 0
