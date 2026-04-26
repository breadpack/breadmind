import pytest
from uuid import uuid4
from breadmind.messenger.acl.cache import VisibleChannelsCache


@pytest.mark.asyncio
async def test_set_then_get(redis_client):
    cache = VisibleChannelsCache(redis_client, ttl_sec=300)
    uid = uuid4()
    cids = [uuid4(), uuid4()]
    await cache.set(user_id=uid, channel_ids=cids)
    got = await cache.get(user_id=uid)
    assert got == cids


@pytest.mark.asyncio
async def test_get_miss_returns_none(redis_client):
    cache = VisibleChannelsCache(redis_client, ttl_sec=300)
    assert await cache.get(user_id=uuid4()) is None


@pytest.mark.asyncio
async def test_invalidate_user(redis_client):
    cache = VisibleChannelsCache(redis_client, ttl_sec=300)
    uid = uuid4()
    await cache.set(user_id=uid, channel_ids=[uuid4()])
    await cache.invalidate_user(uid)
    assert await cache.get(user_id=uid) is None


@pytest.mark.asyncio
async def test_invalidate_workspace(redis_client):
    cache = VisibleChannelsCache(redis_client, ttl_sec=300)
    wid = uuid4()
    uid_a = uuid4()
    uid_b = uuid4()
    await cache.set(user_id=uid_a, channel_ids=[uuid4()], workspace_id=wid)
    await cache.set(user_id=uid_b, channel_ids=[uuid4()], workspace_id=wid)
    await cache.invalidate_workspace(wid)
    assert await cache.get(user_id=uid_a) is None
    assert await cache.get(user_id=uid_b) is None
