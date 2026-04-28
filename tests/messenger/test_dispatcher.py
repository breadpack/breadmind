"""Tests for the outbox -> Redis publish dispatcher."""
from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest

from breadmind.messenger.dispatcher import (
    OutboxDispatcher, dispatch_one_batch,
)


class FakeRedis:
    def __init__(self):
        self.published: list[tuple[str, bytes]] = []

    async def publish(self, channel: str, payload):
        if isinstance(payload, str):
            payload = payload.encode()
        self.published.append((channel, payload))
        return 1


async def _seed_outbox(db, workspace_id, channel_id, event_type, payload):
    from breadmind.messenger.service.outbox_service import enqueue_outbox
    return await enqueue_outbox(
        db, workspace_id=workspace_id, channel_id=channel_id,
        event_type=event_type, payload=payload,
    )


async def test_dispatch_publishes_one_row(test_db):
    redis = FakeRedis()
    await test_db.execute("DELETE FROM message_outbox")  # isolate
    wid, cid = uuid4(), uuid4()
    eid = await _seed_outbox(
        test_db, wid, cid, "message.created",
        {"message_id": str(uuid4()), "channel_id": str(cid)},
    )

    n = await dispatch_one_batch(test_db, redis, batch_size=10)
    assert n == 1
    assert len(redis.published) == 1
    ch, payload = redis.published[0]
    assert ch == f"channel:{cid}.events"
    env = json.loads(payload)
    assert env["type"] == "message.created"
    assert env["payload"]["channel_id"] == str(cid)

    # Row deleted after successful publish
    row = await test_db.fetchrow("SELECT id FROM message_outbox WHERE id=$1", eid)
    assert row is None


async def test_dispatch_zero_when_empty(test_db):
    redis = FakeRedis()
    # Clear any leftover rows from other tests
    await test_db.execute("DELETE FROM message_outbox")
    n = await dispatch_one_batch(test_db, redis, batch_size=10)
    assert n == 0
    assert redis.published == []


async def test_dispatch_respects_batch_size(test_db):
    redis = FakeRedis()
    await test_db.execute("DELETE FROM message_outbox")  # isolate

    wid, cid = uuid4(), uuid4()
    for _ in range(5):
        await _seed_outbox(
            test_db, wid, cid, "message.created", {"channel_id": str(cid)}
        )

    n = await dispatch_one_batch(test_db, redis, batch_size=3)
    assert n == 3
    assert len(redis.published) == 3

    remaining = await test_db.fetchval(
        "SELECT count(*) FROM message_outbox WHERE workspace_id=$1", wid
    )
    assert remaining == 2


async def test_loop_exits_on_cancel(test_db):
    redis = FakeRedis()
    await test_db.execute("DELETE FROM message_outbox")  # isolate

    disp = OutboxDispatcher(test_db, redis, poll_interval=0.05, batch_size=10)
    task = asyncio.create_task(disp.run())
    await asyncio.sleep(0.15)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
