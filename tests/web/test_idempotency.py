"""Tests for the idempotency middleware."""

from __future__ import annotations

import asyncio
import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from breadmind.web.idempotency import (
    CachedResponse,
    IdempotencyConfig,
    IdempotencyStore,
    setup_idempotency,
)


def _make_app(config: IdempotencyConfig | None = None) -> tuple[FastAPI, IdempotencyStore]:
    """Create a minimal FastAPI app with the idempotency middleware."""
    app = FastAPI()
    store = setup_idempotency(app, config)

    call_count: dict[str, int] = {"n": 0}

    @app.post("/do-thing")
    async def do_thing():
        call_count["n"] += 1
        return JSONResponse({"count": call_count["n"]})

    @app.get("/read-thing")
    async def read_thing():
        return JSONResponse({"ok": True})

    @app.put("/update-thing")
    async def update_thing():
        call_count["n"] += 1
        return JSONResponse({"count": call_count["n"]})

    app.state.call_count = call_count
    return app, store


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---- Tests ----


async def test_post_without_key():
    """POST without Idempotency-Key is processed normally every time."""
    app, _ = _make_app()
    async with _client(app) as c:
        r1 = await c.post("/do-thing")
        r2 = await c.post("/do-thing")
    assert r1.json()["count"] == 1
    assert r2.json()["count"] == 2


async def test_post_with_key_first_time():
    """First POST with a key processes normally and caches."""
    app, store = _make_app()
    async with _client(app) as c:
        r = await c.post("/do-thing", headers={"Idempotency-Key": "abc"})
    assert r.status_code == 200
    assert r.json()["count"] == 1
    # Cache entry exists
    cached = await store.get("abc")
    assert cached is not None
    assert cached.status_code == 200


async def test_post_with_key_cached():
    """Same key returns cached response without re-executing."""
    app, _ = _make_app()
    async with _client(app) as c:
        r1 = await c.post("/do-thing", headers={"Idempotency-Key": "k1"})
        r2 = await c.post("/do-thing", headers={"Idempotency-Key": "k1"})
    assert r1.json()["count"] == 1
    assert r2.json()["count"] == 1  # same cached result
    assert app.state.call_count["n"] == 1  # handler called only once


async def test_get_request_passthrough():
    """GET requests bypass the idempotency middleware entirely."""
    app, _ = _make_app()
    async with _client(app) as c:
        r = await c.get("/read-thing", headers={"Idempotency-Key": "ignored"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


async def test_different_keys():
    """Different keys are processed independently."""
    app, _ = _make_app()
    async with _client(app) as c:
        r1 = await c.post("/do-thing", headers={"Idempotency-Key": "a"})
        r2 = await c.post("/do-thing", headers={"Idempotency-Key": "b"})
    assert r1.json()["count"] == 1
    assert r2.json()["count"] == 2


async def test_cache_ttl_expiry():
    """After TTL expires the same key triggers a new execution."""
    config = IdempotencyConfig(cache_ttl=1)
    app, store = _make_app(config)
    async with _client(app) as c:
        r1 = await c.post("/do-thing", headers={"Idempotency-Key": "ttl"})
        assert r1.json()["count"] == 1

        # Manually expire the cached entry
        cached = await store.get("ttl")
        assert cached is not None
        async with store._lock:
            store._cache["ttl"] = CachedResponse(
                status_code=cached.status_code,
                body=cached.body,
                headers=cached.headers,
                created_at=time.monotonic() - 10,  # well past TTL
            )

        r2 = await c.post("/do-thing", headers={"Idempotency-Key": "ttl"})
    assert r2.json()["count"] == 2


async def test_concurrent_same_key():
    """Concurrent requests with the same key return 409 for the second."""
    app = FastAPI()
    setup_idempotency(app)

    started = asyncio.Event()
    proceed = asyncio.Event()

    @app.post("/slow")
    async def slow_endpoint():
        started.set()
        await proceed.wait()
        return JSONResponse({"done": True})

    async with _client(app) as c:
        # Start the first (slow) request
        task1 = asyncio.create_task(
            c.post("/slow", headers={"Idempotency-Key": "dup"})
        )
        await started.wait()

        # Second request with same key while first is processing
        r2 = await c.post("/slow", headers={"Idempotency-Key": "dup"})
        assert r2.status_code == 409

        # Let first complete
        proceed.set()
        r1 = await task1
        assert r1.status_code == 200


async def test_cleanup_expired():
    """cleanup() removes expired entries."""
    config = IdempotencyConfig(cache_ttl=1)
    store = IdempotencyStore(config)

    await store.set("old", CachedResponse(
        status_code=200, body=b"x", headers={}, created_at=time.monotonic() - 100,
    ))
    await store.set("new", CachedResponse(
        status_code=200, body=b"y", headers={}, created_at=time.monotonic(),
    ))

    await store.cleanup()

    assert await store.get("old") is None
    assert await store.get("new") is not None


async def test_config_defaults():
    """IdempotencyConfig has expected defaults."""
    cfg = IdempotencyConfig()
    assert cfg.cache_ttl == 300
    assert cfg.max_cache_size == 10_000
    assert cfg.enabled is True
