"""Notion API HTTP client with 3 rps token bucket + 429/5xx backoff.

Spec: docs/superpowers/specs/2026-04-26-backfill-notion-design.md §5.1
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import aiohttp

from breadmind.kb.backfill.adapters.notion_common import BASE_URL, build_headers

# 3 requests per second → minimum 333 ms between calls.
_MIN_INTERVAL: float = 1 / 3

# Backoff schedule for 429 (no Retry-After) and 5xx responses (seconds).
_BACKOFF_SCHEDULE: tuple[int, ...] = (60, 300, 1800)


class NotionClient:
    """aiohttp-based Notion API client.

    Features:
    - asyncio.Semaphore(1): at most one in-flight HTTP call at a time
    - 3 rps token bucket via ``asyncio.Lock`` + ``last_call`` tracking
    - 429 with ``Retry-After`` header → sleep(Retry-After) then retry
    - 429 without ``Retry-After`` and 5xx → backoff (60 s, 300 s, 1800 s)
    - High-level methods: search / list_block_children / query_database /
      retrieve_page
    """

    def __init__(self, *, token: str) -> None:
        self._token = token
        self._session: aiohttp.ClientSession | None = None
        self._semaphore = asyncio.Semaphore(1)
        self._rate_lock = asyncio.Lock()
        self._last_call: float = 0.0

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # Core request with rate-limiting + retry
    # ------------------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a request to the Notion API.

        Enforces 3 rps token bucket, retries on 429 / 5xx with the schedule
        described in §5.1.
        """
        url = f"{BASE_URL}{path}"
        headers = build_headers(self._token)
        backoff_idx = 0

        while True:
            async with self._semaphore:
                # Token bucket: ensure min 333 ms between calls.
                async with self._rate_lock:
                    now = time.monotonic()
                    elapsed = now - self._last_call
                    if elapsed < _MIN_INTERVAL:
                        await asyncio.sleep(_MIN_INTERVAL - elapsed)
                    self._last_call = time.monotonic()

                session = self._get_session()
                async with session.request(
                    method, url, headers=headers, json=json
                ) as resp:
                    status = resp.status
                    if status == 429:
                        retry_after = resp.headers.get("Retry-After")
                        if retry_after:
                            await asyncio.sleep(float(retry_after))
                        else:
                            if backoff_idx < len(_BACKOFF_SCHEDULE):
                                await asyncio.sleep(_BACKOFF_SCHEDULE[backoff_idx])
                                backoff_idx += 1
                            else:
                                raise aiohttp.ClientResponseError(
                                    request_info=resp.request_info,
                                    history=(),
                                    status=status,
                                )
                        continue
                    if status >= 500:
                        if backoff_idx < len(_BACKOFF_SCHEDULE):
                            await asyncio.sleep(_BACKOFF_SCHEDULE[backoff_idx])
                            backoff_idx += 1
                            continue
                        resp.raise_for_status()
                    resp.raise_for_status()
                    return await resp.json()

    # ------------------------------------------------------------------
    # High-level Notion API surface
    # ------------------------------------------------------------------

    async def search(
        self,
        *,
        filter: dict[str, Any] | None = None,
        sort: dict[str, Any] | None = None,
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        """POST /v1/search — return pages/databases the integration can see."""
        body: dict[str, Any] = {"page_size": page_size}
        if filter is not None:
            body["filter"] = filter
        if sort is not None:
            body["sort"] = sort
        if start_cursor is not None:
            body["start_cursor"] = start_cursor
        return await self.request("POST", "/search", json=body)

    async def list_block_children(
        self,
        block_id: str,
        *,
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        """GET /v1/blocks/{block_id}/children."""
        path = f"/blocks/{block_id}/children"
        params: dict[str, Any] = {"page_size": page_size}
        if start_cursor is not None:
            params["start_cursor"] = start_cursor
        # Build query string manually (aiohttp params not used here — we stay
        # on the single request() abstraction that takes json= for bodies).
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return await self.request("GET", f"{path}?{qs}")

    async def query_database(
        self,
        db_id: str,
        *,
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        """POST /v1/databases/{db_id}/query."""
        body: dict[str, Any] = {"page_size": page_size}
        if start_cursor is not None:
            body["start_cursor"] = start_cursor
        return await self.request("POST", f"/databases/{db_id}/query", json=body)

    async def retrieve_page(self, page_id: str) -> dict[str, Any]:
        """GET /v1/pages/{page_id}."""
        return await self.request("GET", f"/pages/{page_id}")
