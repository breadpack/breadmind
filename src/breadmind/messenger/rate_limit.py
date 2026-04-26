"""Tier-based rate limiter. Sliding window over 60 seconds."""
from __future__ import annotations
import os
import time
from typing import Final


_DEFAULT_LIMITS: Final[dict[int, int]] = {1: 1, 2: 50, 3: 500}
_WINDOW_SEC: Final[int] = 60


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int, limit: int):
        super().__init__(f"limit {limit}/min exceeded; retry after {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds
        self.limit = limit


class RateLimiter:
    def __init__(self, redis, *, tier_limits: dict[int, int] | None = None):
        self._r = redis
        self._limits = tier_limits or _DEFAULT_LIMITS

    async def check_and_consume(self, token_id: str, *, tier: int) -> None:
        limit = self._limits[tier]
        now = int(time.time())
        key = f"rl:{token_id}:{tier}"
        cutoff = now - _WINDOW_SEC
        # Member must be unique per call; append random bytes so same-second
        # calls don't collide and overwrite each other in the sorted set.
        member = f"{now}-{token_id}-{os.urandom(4).hex()}"
        async with self._r.pipeline(transaction=True) as pipe:
            await pipe.zremrangebyscore(key, 0, cutoff)
            await pipe.zcard(key)
            await pipe.zadd(key, {member: now})
            await pipe.expire(key, _WINDOW_SEC + 5)
            results = await pipe.execute()
        count = results[1]
        if count >= limit:
            earliest = await self._r.zrange(key, 0, 0, withscores=True)
            retry = _WINDOW_SEC - (now - int(earliest[0][1])) + 1 if earliest else _WINDOW_SEC
            raise RateLimitExceeded(retry_after_seconds=max(1, retry), limit=limit)
