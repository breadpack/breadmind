"""PersonalCache tests."""
import asyncio

import pytest


@pytest.mark.asyncio
async def test_set_and_get():
    from breadmind.personal.cache import PersonalCache
    cache = PersonalCache(default_ttl=10)
    await cache.set("task:pending:default", ["task1", "task2"])
    result = await cache.get("task:pending:default")
    assert result == ["task1", "task2"]


@pytest.mark.asyncio
async def test_expired_returns_none():
    from breadmind.personal.cache import PersonalCache
    cache = PersonalCache(default_ttl=0)  # 0 second TTL
    await cache.set("key", "value", ttl=0)
    await asyncio.sleep(0.1)
    result = await cache.get("key")
    assert result is None


@pytest.mark.asyncio
async def test_invalidate_domain():
    from breadmind.personal.cache import PersonalCache
    cache = PersonalCache()
    await cache.set("task:pending:default", [1])
    await cache.set("task:done:default", [2])
    await cache.set("event:upcoming:default", [3])
    await cache.invalidate("task")
    assert await cache.get("task:pending:default") is None
    assert await cache.get("task:done:default") is None
    assert await cache.get("event:upcoming:default") == [3]


@pytest.mark.asyncio
async def test_invalidate_all():
    from breadmind.personal.cache import PersonalCache
    cache = PersonalCache()
    await cache.set("a", 1)
    await cache.set("b", 2)
    await cache.invalidate_all()
    assert await cache.get("a") is None
    assert await cache.get("b") is None
