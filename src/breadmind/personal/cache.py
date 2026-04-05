"""In-memory cache for personal assistant data.

Caches tasks, events, and contacts with TTL. Automatically invalidated
on writes (create/update/delete). Prefetches on startup and periodically.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from breadmind.utils.helpers import cancel_task_safely

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    data: Any
    expires_at: float

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class PersonalCache:
    """Fast in-memory cache for personal assistant data."""

    def __init__(self, default_ttl: int = 60) -> None:
        self._cache: dict[str, CacheEntry] = {}
        self._default_ttl = default_ttl  # seconds
        self._lock = asyncio.Lock()
        self._registry: Any = None
        self._prefetch_task: asyncio.Task | None = None

    def set_registry(self, registry: Any) -> None:
        self._registry = registry

    async def get(self, key: str) -> Any | None:
        """Get cached value. Returns None if expired or missing."""
        entry = self._cache.get(key)
        if entry and not entry.is_expired:
            return entry.data
        return None

    async def set(self, key: str, data: Any, ttl: int | None = None) -> None:
        """Set cache value with TTL."""
        self._cache[key] = CacheEntry(
            data=data,
            expires_at=time.time() + (ttl or self._default_ttl),
        )

    async def invalidate(self, domain: str) -> None:
        """Invalidate all cache entries for a domain (task, event, contact)."""
        keys_to_remove = [k for k in self._cache if k.startswith(f"{domain}:")]
        for k in keys_to_remove:
            del self._cache[k]
        logger.debug("Cache invalidated for domain: %s (%d entries)", domain, len(keys_to_remove))

    async def invalidate_all(self) -> None:
        """Clear entire cache."""
        self._cache.clear()

    async def prefetch(self) -> None:
        """Prefetch commonly needed data into cache."""
        if not self._registry:
            return

        # Prefetch pending tasks
        try:
            adapter = self._registry.get_adapter("task", "builtin")
            tasks = await adapter.list_items(filters={"user_id": "default", "status": "pending"}, limit=50)
            await self.set("task:pending:default", tasks, ttl=120)
            logger.debug("Prefetched %d pending tasks", len(tasks))
        except Exception:
            pass

        # Prefetch upcoming events (next 48h)
        try:
            from datetime import datetime, timedelta, timezone
            now = datetime.now(timezone.utc)
            adapter = self._registry.get_adapter("event", "builtin")
            events = await adapter.list_items(
                filters={"user_id": "default", "start_after": now, "start_before": now + timedelta(hours=48)},
                limit=20,
            )
            await self.set("event:upcoming:default", events, ttl=120)
            logger.debug("Prefetched %d upcoming events", len(events))
        except Exception:
            pass

    async def start_prefetch_loop(self, interval: int = 120) -> None:
        """Start background prefetch loop."""
        async def _loop() -> None:
            while True:
                try:
                    await self.prefetch()
                except Exception:
                    logger.exception("Prefetch failed")
                await asyncio.sleep(interval)

        self._prefetch_task = asyncio.create_task(_loop())
        logger.info("PersonalCache prefetch loop started (interval=%ds)", interval)

    async def stop(self) -> None:
        await cancel_task_safely(self._prefetch_task)


# Singleton instance
_cache = PersonalCache(default_ttl=60)


def get_cache() -> PersonalCache:
    return _cache
