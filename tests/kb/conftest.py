"""Shared fixtures for KB test suite."""
from __future__ import annotations

import pytest
import pytest_asyncio


@pytest.fixture
def sample_vocab() -> list[str]:
    return ["Acme Corp", "Globex", "Initech"]


@pytest_asyncio.fixture
async def fake_redis():
    import fakeredis.aioredis
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()
