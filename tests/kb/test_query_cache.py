from breadmind.kb.query_cache import QueryCache


async def test_miss_then_hit(fake_redis):
    cache = QueryCache(redis=fake_redis, ttl_seconds=300)
    hit1 = await cache.get("hello", "U1", "p1")
    assert hit1 is None
    await cache.set("hello", "U1", "p1", "cached-answer")
    hit2 = await cache.get("hello", "U1", "p1")
    assert hit2 == "cached-answer"


async def test_key_varies_by_user(fake_redis):
    cache = QueryCache(redis=fake_redis, ttl_seconds=300)
    await cache.set("hello", "U1", "p1", "a1")
    assert await cache.get("hello", "U2", "p1") is None


async def test_ttl_applied(fake_redis):
    cache = QueryCache(redis=fake_redis, ttl_seconds=123)
    await cache.set("q", "u", "p", "v")
    # fakeredis supports ttl lookup
    keys = await fake_redis.keys("*")
    assert keys, "cache key was not written"
    ttl = await fake_redis.ttl(keys[0])
    assert 0 < ttl <= 123
