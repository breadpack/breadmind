"""Tests for IdempotencyStore (Redis-backed, 24h TTL)."""
import pytest
from uuid import uuid4
from breadmind.messenger.idempotency import (
    IdempotencyStore, IdempotencyConflict, hash_request,
)


@pytest.mark.asyncio
async def test_first_call_stores_response(redis_client):
    store = IdempotencyStore(redis_client)
    key = str(uuid4())
    cached = await store.get_or_lock(key, request_hash="reqhash")
    assert cached is None  # newly acquired lock
    await store.put(key, request_hash="reqhash", status=201, body=b'{"ok":true}')
    cached2 = await store.get_or_lock(key, request_hash="reqhash")
    assert cached2 is not None
    assert cached2 is not store.IN_PROGRESS_SENTINEL
    assert cached2.status == 201
    assert cached2.body == b'{"ok":true}'


@pytest.mark.asyncio
async def test_request_hash_mismatch_raises(redis_client):
    store = IdempotencyStore(redis_client)
    key = str(uuid4())
    await store.put(key, request_hash="A", status=201, body=b"x")
    with pytest.raises(IdempotencyConflict):
        await store.get_or_lock(key, request_hash="B")


@pytest.mark.asyncio
async def test_lock_concurrent_request(redis_client):
    """Second request with same key (still locked) returns IN_PROGRESS sentinel."""
    store = IdempotencyStore(redis_client)
    key = str(uuid4())
    cached = await store.get_or_lock(key, request_hash="A")
    assert cached is None  # acquired lock
    cached2 = await store.get_or_lock(key, request_hash="A")
    assert cached2 is store.IN_PROGRESS_SENTINEL


def test_hash_request_deterministic():
    h1 = hash_request("POST", "/messages", b'{"text":"hi"}')
    h2 = hash_request("POST", "/messages", b'{"text":"hi"}')
    assert h1 == h2
    h3 = hash_request("POST", "/messages", b'{"text":"different"}')
    assert h1 != h3
