"""HTTP helpers for the Confluence backfill adapter.

Re-implements ``_get_with_retry`` and ``_build_auth_header`` inline (zero
coupling to ConfluenceConnector instance state — spec §7, plan note 7).
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

import aiohttp

from breadmind.kb.connectors.confluence import ConfluenceConnector

logger = logging.getLogger(__name__)

# Reuse connector constants without modifying the connector.
_PAGE_LIMIT: int = ConfluenceConnector._PAGE_LIMIT
_BACKOFF_SECONDS: tuple[int, ...] = ConfluenceConnector._BACKOFF_SECONDS
_CHUNK_CHAR_BUDGET: int = ConfluenceConnector._CHUNK_CHAR_BUDGET

_EXPAND = (
    "body.storage,version,history,metadata.labels,"
    "restrictions.read,ancestors,space"
)


async def build_auth_header(vault: Any, credentials_ref: str) -> str:
    """Encode vault credentials as a Basic auth header value."""
    raw = await vault.retrieve(credentials_ref)
    if not raw:
        raise RuntimeError(
            f"Confluence credential not in vault: {credentials_ref}"
        )
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def acquire_session(
    session_override: aiohttp.ClientSession | None,
) -> aiohttp.ClientSession:
    """Return the override session or open a fresh one."""
    if session_override is not None:
        return session_override
    return aiohttp.ClientSession()


async def release_session(
    session: aiohttp.ClientSession,
    session_override: aiohttp.ClientSession | None,
) -> None:
    """Close the session unless it was injected as an override."""
    if session_override is None:
        await session.close()


async def get_with_retry(
    session: aiohttp.ClientSession,
    url: str,
    params: dict | None,
    auth: str,
) -> dict:
    """GET with Retry-After + exponential back-off on 429/5xx.

    Intentionally re-implemented (not imported from ConfluenceConnector)
    so the adapter has zero coupling to the connector's instance state
    (plan self-review note 7).
    """
    backoffs = list(_BACKOFF_SECONDS)
    while True:
        async with session.get(
            url, params=params, headers={"Authorization": auth}
        ) as resp:
            if resp.status == 429:
                retry_after = int(resp.headers.get("Retry-After", "0"))
                wait = retry_after if retry_after > 0 else (
                    backoffs.pop(0) if backoffs else _BACKOFF_SECONDS[-1]
                )
                logger.warning(
                    "Confluence 429; sleeping %ds (Retry-After=%s)",
                    wait, resp.headers.get("Retry-After"),
                )
                await asyncio.sleep(wait)
                continue
            if 500 <= resp.status < 600 and backoffs:
                wait = backoffs.pop(0)
                logger.warning("Confluence %d; sleeping %ds", resp.status, wait)
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            return await resp.json()


async def fetch_page_by_id(
    session: aiohttp.ClientSession,
    base_url: str,
    page_id: str,
    auth: str,
) -> dict:
    """Fetch a single Confluence page by its numeric ID."""
    url = f"{base_url}/rest/api/content/{page_id}"
    return await get_with_retry(session, url, {"expand": _EXPAND}, auth)
