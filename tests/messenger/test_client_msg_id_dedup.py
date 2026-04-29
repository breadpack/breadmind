"""client_msg_id body-keyed dedup: same key returns same Message row, no duplicate INSERT."""
from __future__ import annotations
from uuid import uuid4
from unittest.mock import AsyncMock

from breadmind.messenger.idempotency import ClientMsgIdDedup


async def test_dedup_miss_returns_none():
    redis = AsyncMock()
    redis.get.return_value = None
    redis.set.return_value = True
    d = ClientMsgIdDedup(redis)
    sender = uuid4()
    channel = uuid4()
    cmid = uuid4()
    got = await d.lookup(sender_id=sender, channel_id=channel, client_msg_id=cmid)
    assert got is None


async def test_dedup_remember_then_lookup_hits():
    redis = AsyncMock()
    storage: dict[str, str] = {}

    async def _set(k, v, ex=None, nx=None):
        if nx and k in storage:
            return False
        storage[k] = v
        return True

    async def _get(k):
        return storage.get(k)

    redis.set = AsyncMock(side_effect=_set)
    redis.get = AsyncMock(side_effect=_get)
    d = ClientMsgIdDedup(redis)
    sender = uuid4()
    channel = uuid4()
    cmid = uuid4()
    msg_id = uuid4()
    await d.remember(
        sender_id=sender, channel_id=channel,
        client_msg_id=cmid, message_id=msg_id,
    )
    got = await d.lookup(sender_id=sender, channel_id=channel, client_msg_id=cmid)
    assert got == msg_id


async def test_dedup_remember_uses_24h_ttl():
    """remember() must call redis.set with ex=24*3600 to lock the TTL contract."""
    redis = AsyncMock()
    redis.set.return_value = True
    d = ClientMsgIdDedup(redis)
    await d.remember(
        sender_id=uuid4(), channel_id=uuid4(),
        client_msg_id=uuid4(), message_id=uuid4(),
    )
    _, kwargs = redis.set.call_args
    assert kwargs.get("ex") == 24 * 3600


async def test_dedup_different_channel_different_key():
    redis = AsyncMock()
    storage: dict[str, str] = {}

    async def _set(k, v, ex=None, nx=None):
        storage[k] = v
        return True

    async def _get(k):
        return storage.get(k)

    redis.set = AsyncMock(side_effect=_set)
    redis.get = AsyncMock(side_effect=_get)
    d = ClientMsgIdDedup(redis)
    sender = uuid4()
    ch1 = uuid4()
    ch2 = uuid4()
    cmid = uuid4()
    msg_id = uuid4()
    await d.remember(
        sender_id=sender, channel_id=ch1,
        client_msg_id=cmid, message_id=msg_id,
    )
    got = await d.lookup(sender_id=sender, channel_id=ch2, client_msg_id=cmid)
    assert got is None
