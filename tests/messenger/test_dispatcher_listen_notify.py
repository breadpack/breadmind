"""LISTEN/NOTIFY wakes dispatcher from idle within 1s of INSERT.

Validates that ``OutboxDispatcher`` wakes within ~ms of an outbox row
INSERT (via ``LISTEN outbox_new`` paired with the AFTER INSERT trigger
introduced in migration 021), instead of waiting up to ``poll_interval``
for the safety polling tick.

Marked ``relay_integration`` because it requires a live PostgreSQL
connection (LISTEN/NOTIFY is a server feature; not reproducible offline).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from breadmind.messenger.dispatcher import OutboxDispatcher


class _Publisher:
    def __init__(self):
        self.events: asyncio.Queue = asyncio.Queue()

    async def publish(self, channel: str, payload: str | bytes) -> int:
        await self.events.put(
            (channel, payload if isinstance(payload, str) else payload.decode())
        )
        return 1


@pytest.mark.relay_integration
async def test_listen_notify_wakes_dispatcher_under_1s(test_db, seed_channel):
    """Insert into outbox while dispatcher idle; expect publish within 1s."""
    wid, channel_id, _owner_id = seed_channel

    # Isolate from any leftover rows so the dispatcher's first batch is empty
    # and it parks on the LISTEN/safety-poll wait.
    await test_db.execute("DELETE FROM message_outbox")

    pub = _Publisher()
    # Pass the Database/pool wrapper directly: the dispatcher's listen loop
    # acquires its own connection for add_listener while batches use a
    # separate acquire. poll_interval=5s means a successful sub-1s wakeup
    # *must* come from NOTIFY (the safety poll won't fire that fast).
    disp = OutboxDispatcher(test_db, pub, poll_interval=5.0, batch_size=10)
    task = asyncio.create_task(disp.run())
    try:
        # Give the LISTEN connection time to register before we INSERT.
        await asyncio.sleep(0.2)

        expires = datetime.now(timezone.utc) + timedelta(seconds=300)
        await test_db.execute(
            "INSERT INTO message_outbox "
            "(id, workspace_id, channel_id, event_type, payload, expires_at) "
            "VALUES ($1, $2, $3, 'message_created', $4::jsonb, $5)",
            uuid4(), wid, channel_id, json.dumps({"hello": "world"}), expires,
        )

        ch, _payload = await asyncio.wait_for(pub.events.get(), timeout=1.0)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert ch == f"channel:{channel_id}.events"
