"""Idempotency middleware for POST/PUT/PATCH request deduplication.

Clients include an ``Idempotency-Key`` header; the middleware caches the
response for that key so that retries return the same result without
re-executing the handler.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response as StarletteResponse

logger = logging.getLogger(__name__)

IDEMPOTENCY_HEADER = "Idempotency-Key"
IDEMPOTENT_METHODS = {"POST", "PUT", "PATCH"}


@dataclass
class IdempotencyConfig:
    """Configuration for the idempotency middleware."""

    cache_ttl: int = 300  # seconds
    max_cache_size: int = 10_000
    enabled: bool = True


@dataclass
class CachedResponse:
    """Stored response for an idempotency key."""

    status_code: int
    body: bytes
    headers: dict[str, str]
    created_at: float  # time.monotonic


class IdempotencyStore:
    """In-memory, concurrency-safe store for idempotent responses."""

    def __init__(self, config: IdempotencyConfig) -> None:
        self._config = config
        self._cache: dict[str, CachedResponse] = {}
        self._processing: set[str] = set()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> CachedResponse | None:
        async with self._lock:
            cached = self._cache.get(key)
            if cached is None:
                return None
            if time.monotonic() - cached.created_at > self._config.cache_ttl:
                self._cache.pop(key, None)
                return None
            return cached

    async def set(self, key: str, response: CachedResponse) -> None:
        async with self._lock:
            # Evict oldest entries when cache is full
            if len(self._cache) >= self._config.max_cache_size:
                oldest_key = min(self._cache, key=lambda k: self._cache[k].created_at)
                del self._cache[oldest_key]
            self._cache[key] = response

    async def is_processing(self, key: str) -> bool:
        async with self._lock:
            return key in self._processing

    async def mark_processing(self, key: str) -> None:
        async with self._lock:
            self._processing.add(key)

    async def unmark_processing(self, key: str) -> None:
        async with self._lock:
            self._processing.discard(key)

    async def cleanup(self) -> None:
        """Remove expired entries from the cache."""
        now = time.monotonic()
        async with self._lock:
            expired = [
                k for k, v in self._cache.items()
                if now - v.created_at > self._config.cache_ttl
            ]
            for k in expired:
                del self._cache[k]


class _IdempotencyMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces idempotency via a request header."""

    def __init__(self, app, store: IdempotencyStore) -> None:  # noqa: ANN001
        super().__init__(app)
        self._store = store

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> StarletteResponse:
        # Only apply to mutating methods
        if request.method not in IDEMPOTENT_METHODS:
            return await call_next(request)

        # If no idempotency key header, pass through normally
        idem_key = request.headers.get(IDEMPOTENCY_HEADER)
        if not idem_key:
            return await call_next(request)

        # Check cache hit
        cached = await self._store.get(idem_key)
        if cached is not None:
            return Response(
                content=cached.body,
                status_code=cached.status_code,
                headers=cached.headers,
            )

        # Conflict: another request with the same key is still being processed
        if await self._store.is_processing(idem_key):
            return Response(
                content=b'{"error":"Duplicate request is already being processed"}',
                status_code=409,
                media_type="application/json",
            )

        # Mark as processing and execute
        await self._store.mark_processing(idem_key)
        try:
            response = await call_next(request)

            # Read the response body so we can cache it
            body = b""
            async for chunk in response.body_iterator:  # type: ignore[union-attr]
                if isinstance(chunk, str):
                    body += chunk.encode("utf-8")
                else:
                    body += chunk

            # Collect headers we want to cache (skip hop-by-hop)
            headers = {
                k: v for k, v in response.headers.items()
                if k.lower() not in ("transfer-encoding",)
            }

            await self._store.set(
                idem_key,
                CachedResponse(
                    status_code=response.status_code,
                    body=body,
                    headers=headers,
                    created_at=time.monotonic(),
                ),
            )

            return Response(
                content=body,
                status_code=response.status_code,
                headers=headers,
            )
        finally:
            await self._store.unmark_processing(idem_key)


def setup_idempotency(
    app: FastAPI, config: IdempotencyConfig | None = None
) -> IdempotencyStore:
    """Register the idempotency middleware on *app*.

    Returns the :class:`IdempotencyStore` for testing or manual cleanup.
    """
    config = config or IdempotencyConfig()
    if not config.enabled:
        return IdempotencyStore(config)

    store = IdempotencyStore(config)
    app.add_middleware(_IdempotencyMiddleware, store=store)
    return store
