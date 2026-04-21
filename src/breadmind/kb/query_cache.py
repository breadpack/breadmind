# src/breadmind/kb/query_cache.py
from __future__ import annotations

import hashlib

_DEFAULT_TTL = 300  # 5 minutes per spec §8.6


class QueryCache:
    """Redis-backed per-query cache. Key = sha256(query|user_id|project_id).

    Deviation from plan: get() uses a decode-safe wrapper over Redis get to
    support decode_responses=False fake_redis fixture used across the KB test
    suite (preserved from P1 to avoid regression). The isinstance guard makes
    it work for both decode_responses=True and False clients.
    """

    def __init__(self, redis, ttl_seconds: int = _DEFAULT_TTL) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    @staticmethod
    def _key(query: str, user_id: str, project_id: str) -> str:
        h = hashlib.sha256(
            f"{query}\x00{user_id}\x00{project_id}".encode("utf-8")
        ).hexdigest()
        return f"breadmind:kb:qcache:{h}"

    async def get(self, query: str, user_id: str, project_id: str) -> str | None:
        raw = await self._redis.get(self._key(query, user_id, project_id))
        if raw is None:
            return None
        return raw.decode("utf-8") if isinstance(raw, bytes) else raw

    async def set(
        self, query: str, user_id: str, project_id: str, value: str,
    ) -> None:
        await self._redis.set(
            self._key(query, user_id, project_id), value, ex=self._ttl,
        )
