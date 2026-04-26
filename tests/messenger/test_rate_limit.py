import pytest
from breadmind.messenger.rate_limit import RateLimiter, RateLimitExceeded


@pytest.mark.asyncio
async def test_under_limit_passes(redis_client):
    rl = RateLimiter(redis_client)
    for _ in range(5):
        await rl.check_and_consume("token1", tier=2)


@pytest.mark.asyncio
async def test_over_limit_raises(redis_client):
    rl = RateLimiter(redis_client, tier_limits={1: 1, 2: 3, 3: 10})
    await rl.check_and_consume("t", tier=2)
    await rl.check_and_consume("t", tier=2)
    await rl.check_and_consume("t", tier=2)
    with pytest.raises(RateLimitExceeded) as exc:
        await rl.check_and_consume("t", tier=2)
    assert exc.value.retry_after_seconds > 0


@pytest.mark.asyncio
async def test_independent_per_token(redis_client):
    rl = RateLimiter(redis_client, tier_limits={1: 1, 2: 1, 3: 1})
    await rl.check_and_consume("a", tier=2)
    await rl.check_and_consume("b", tier=2)  # different token, not blocked
