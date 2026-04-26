"""Unit tests for NotionClient wrapper (Task 2).

Covers:
- 3 rps token bucket: 333ms min gap between calls
- 429 + Retry-After header → sleep(N) then retry
- 429 without Retry-After → backoff (60, 300, 1800)
- 5xx → same backoff as 429 without Retry-After
- Semaphore(1) concurrency guard
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breadmind.kb.backfill.adapters.notion_client import NotionClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_json_response(data: dict, status: int = 200):
    """Build a minimal aiohttp response mock."""
    resp = MagicMock()
    resp.status = status
    resp.headers = {}
    resp.json = AsyncMock(return_value=data)
    if status >= 400:
        from aiohttp import ClientResponseError
        resp.raise_for_status = MagicMock(
            side_effect=ClientResponseError(
                request_info=MagicMock(), history=(), status=status
            )
        )
    else:
        resp.raise_for_status = MagicMock()
    # Support async context manager
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _make_session(*responses):
    """Build a fake aiohttp.ClientSession that returns *responses* in order."""
    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    resp_iter = iter(responses)

    def _request(*_a, **_kw):
        r = next(resp_iter)
        r.__aenter__ = AsyncMock(return_value=r)
        r.__aexit__ = AsyncMock(return_value=False)
        return r

    session.request = _request
    return session


# ---------------------------------------------------------------------------
# Token bucket: 333ms gap enforced
# ---------------------------------------------------------------------------


async def test_token_bucket_enforces_333ms_gap():
    """Three rapid calls should result in asyncio.sleep being called to space
    them at least 1/3 s apart."""
    client = NotionClient(token="secret_x")

    call_times: list[float] = []
    real_monotonic = 0.0

    def fake_monotonic():
        return real_monotonic

    ok_resp = _make_json_response({"object": "list", "results": []})

    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()

    sleep_calls: list[float] = []

    async def fake_sleep(n: float) -> None:
        nonlocal real_monotonic
        sleep_calls.append(n)
        real_monotonic += n

    def fake_request(*_a, **_kw):
        nonlocal real_monotonic
        call_times.append(real_monotonic)
        r = MagicMock()
        r.status = 200
        r.headers = {}
        r.raise_for_status = MagicMock()
        r.json = AsyncMock(return_value={"object": "list", "results": []})
        r.__aenter__ = AsyncMock(return_value=r)
        r.__aexit__ = AsyncMock(return_value=False)
        return r

    session.request = fake_request
    client._session = session

    with (
        patch("breadmind.kb.backfill.adapters.notion_client.time.monotonic", fake_monotonic),
        patch("asyncio.sleep", fake_sleep),
    ):
        for _ in range(3):
            await client.request("GET", "/users/me")

    # At least one sleep must have been issued to enforce rate limiting
    assert len(sleep_calls) >= 1
    # Every sleep must be <= 1/3 second (the bucket gap)
    for s in sleep_calls:
        assert s <= 1 / 3 + 0.01


# ---------------------------------------------------------------------------
# 429 + Retry-After header
# ---------------------------------------------------------------------------


async def test_429_with_retry_after_sleeps_retry_after_value():
    client = NotionClient(token="secret_x")

    from aiohttp import ClientResponseError

    # First call: 429 with Retry-After: 7
    r429 = MagicMock()
    r429.status = 429
    r429.headers = {"Retry-After": "7"}
    r429.raise_for_status = MagicMock(
        side_effect=ClientResponseError(
            request_info=MagicMock(), history=(), status=429
        )
    )
    r429.json = AsyncMock(return_value={})
    r429.__aenter__ = AsyncMock(return_value=r429)
    r429.__aexit__ = AsyncMock(return_value=False)

    # Second call: success
    r200 = _make_json_response({"results": [], "has_more": False})
    r200.__aenter__ = AsyncMock(return_value=r200)
    r200.__aexit__ = AsyncMock(return_value=False)

    call_count = 0

    def fake_request(*_a, **_kw):
        nonlocal call_count
        call_count += 1
        return r429 if call_count == 1 else r200

    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    session.request = fake_request
    client._session = session

    sleep_calls: list[float] = []

    async def fake_sleep(n: float) -> None:
        sleep_calls.append(n)

    with patch("asyncio.sleep", fake_sleep):
        result = await client.request("GET", "/users/me")

    # Must have slept the Retry-After value (7)
    assert any(abs(s - 7) < 0.5 for s in sleep_calls), f"sleep calls: {sleep_calls}"
    assert call_count == 2


# ---------------------------------------------------------------------------
# 429 without Retry-After → backoff schedule (60, 300, 1800)
# ---------------------------------------------------------------------------


async def test_429_without_retry_after_uses_backoff_schedule():
    from aiohttp import ClientResponseError

    client = NotionClient(token="secret_x")

    call_count = 0

    def fake_request(*_a, **_kw):
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            r = MagicMock()
            r.status = 429
            r.headers = {}  # no Retry-After
            r.raise_for_status = MagicMock(
                side_effect=ClientResponseError(
                    request_info=MagicMock(), history=(), status=429
                )
            )
            r.json = AsyncMock(return_value={})
            r.__aenter__ = AsyncMock(return_value=r)
            r.__aexit__ = AsyncMock(return_value=False)
            return r
        else:
            return _make_json_response({"results": []})

    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    session.request = fake_request
    client._session = session

    sleep_calls: list[float] = []

    async def fake_sleep(n: float) -> None:
        sleep_calls.append(n)

    with patch("asyncio.sleep", fake_sleep):
        await client.request("GET", "/users/me")

    # First three retries should use the backoff schedule
    backoff_sleeps = [s for s in sleep_calls if s >= 60]
    assert backoff_sleeps[0] == 60
    assert backoff_sleeps[1] == 300


# ---------------------------------------------------------------------------
# 5xx → same backoff
# ---------------------------------------------------------------------------


async def test_5xx_uses_same_backoff_schedule():
    from aiohttp import ClientResponseError

    client = NotionClient(token="secret_x")
    call_count = 0

    def fake_request(*_a, **_kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            r = MagicMock()
            r.status = 502
            r.headers = {}
            r.raise_for_status = MagicMock(
                side_effect=ClientResponseError(
                    request_info=MagicMock(), history=(), status=502
                )
            )
            r.json = AsyncMock(return_value={})
            r.__aenter__ = AsyncMock(return_value=r)
            r.__aexit__ = AsyncMock(return_value=False)
            return r
        return _make_json_response({"results": []})

    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    session.request = fake_request
    client._session = session

    sleep_calls: list[float] = []

    async def fake_sleep(n: float) -> None:
        sleep_calls.append(n)

    with patch("asyncio.sleep", fake_sleep):
        await client.request("GET", "/some-path")

    assert any(s == 60 for s in sleep_calls)


# ---------------------------------------------------------------------------
# Semaphore / concurrency: at most 1 concurrent HTTP call
# ---------------------------------------------------------------------------


async def test_concurrency_limited_to_one():
    """Two concurrent request() calls should be serialised."""
    client = NotionClient(token="secret_x")

    concurrent_count = 0
    max_concurrent = 0

    async def fake_sleep(_n: float) -> None:
        pass  # suppress rate-limit sleeps

    def slow_request(*_a, **_kw):
        """Returns a context manager that tracks concurrency."""
        class _CM:
            async def __aenter__(self_):
                nonlocal concurrent_count, max_concurrent
                concurrent_count += 1
                max_concurrent = max(max_concurrent, concurrent_count)
                await asyncio.sleep(0)  # yield to allow another task in
                r = MagicMock()
                r.status = 200
                r.headers = {}
                r.raise_for_status = MagicMock()
                r.json = AsyncMock(return_value={"results": []})
                return r

            async def __aexit__(self_, *_):
                nonlocal concurrent_count
                concurrent_count -= 1
                return False

        return _CM()

    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    session.request = slow_request
    client._session = session

    with patch("asyncio.sleep", fake_sleep):
        await asyncio.gather(
            client.request("GET", "/a"),
            client.request("GET", "/b"),
        )

    assert max_concurrent == 1, f"max concurrent was {max_concurrent}"


# ---------------------------------------------------------------------------
# High-level method surface: search / list_block_children / query_database
# ---------------------------------------------------------------------------


async def test_search_returns_results():
    client = NotionClient(token="secret_x")
    data = {"object": "list", "results": [{"id": "page1"}], "has_more": False, "next_cursor": None}
    session = _make_session(_make_json_response(data))
    client._session = session

    with patch("asyncio.sleep", AsyncMock()):
        result = await client.search()

    assert result["results"] == [{"id": "page1"}]


async def test_list_block_children_passes_start_cursor():
    client = NotionClient(token="secret_x")
    data = {"results": [], "has_more": False, "next_cursor": None}
    session = _make_session(_make_json_response(data))
    client._session = session

    with patch("asyncio.sleep", AsyncMock()):
        result = await client.list_block_children("block-abc", start_cursor="cur1")

    assert result["results"] == []


async def test_query_database_returns_rows():
    client = NotionClient(token="secret_x")
    data = {"results": [{"id": "row1"}], "has_more": False, "next_cursor": None}
    session = _make_session(_make_json_response(data))
    client._session = session

    with patch("asyncio.sleep", AsyncMock()):
        result = await client.query_database("db-xyz")

    assert result["results"][0]["id"] == "row1"
