from breadmind.kb.query_cache import QueryCache
from breadmind.kb.quota import QuotaTracker


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


async def test_quota_charge_and_exceed(fake_redis):
    q = QuotaTracker(redis=fake_redis, user_daily_tokens=100)
    assert not await q.is_exceeded("U1")
    await q.charge("U1", 60)
    assert not await q.is_exceeded("U1")
    await q.charge("U1", 50)
    assert await q.is_exceeded("U1")


async def test_quota_per_user_isolated(fake_redis):
    q = QuotaTracker(redis=fake_redis, user_daily_tokens=100)
    await q.charge("U1", 200)
    assert await q.is_exceeded("U1")
    assert not await q.is_exceeded("U2")


async def test_quota_counter_has_ttl(fake_redis):
    q = QuotaTracker(redis=fake_redis, user_daily_tokens=100)
    await q.charge("U1", 10)
    keys = await fake_redis.keys("breadmind:kb:quota:*")
    assert keys
    ttl = await fake_redis.ttl(keys[0])
    assert 0 < ttl <= 86400
