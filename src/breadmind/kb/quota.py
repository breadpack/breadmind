from __future__ import annotations

_DEFAULT_USER_DAILY = 100_000  # spec §8.6: 100k tokens/user/day
_SECONDS_PER_DAY = 86_400


class QuotaTracker:
    """Per-user daily token counter stored in Redis. Key rolls over every 24h
    via TTL. `is_exceeded()` returns True once the user hits the limit, and
    the caller is expected to downgrade to "검색만 모드" (search-only)."""

    def __init__(self, redis, user_daily_tokens: int = _DEFAULT_USER_DAILY) -> None:
        self._redis = redis
        self._limit = user_daily_tokens

    @staticmethod
    def _key(user_id: str) -> str:
        return f"breadmind:kb:quota:{user_id}"

    async def charge(self, user_id: str, tokens: int) -> int:
        key = self._key(user_id)
        new_value = await self._redis.incrby(key, int(tokens))
        # set TTL only once (on first increment of the rolling window)
        if new_value == tokens:
            await self._redis.expire(key, _SECONDS_PER_DAY)
        return int(new_value)

    async def is_exceeded(self, user_id: str) -> bool:
        raw = await self._redis.get(self._key(user_id))
        used = int(raw) if raw is not None else 0
        return used >= self._limit
