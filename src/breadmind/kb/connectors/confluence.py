"""Confluence REST ingestion connector.

Incrementally polls Atlassian Confluence Cloud/Server for pages updated
since the stored cursor, converts storage-format HTML to Markdown, and
feeds each page through the KnowledgeExtractor + ReviewQueue pipeline.
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import logging
import uuid
from dataclasses import dataclass
from typing import Any, ClassVar

import aiohttp
from markdownify import markdownify as md

from breadmind.kb.connectors.base import BaseConnector, SyncResult
from breadmind.kb.connectors.rate_limit import (
    BudgetExceeded,
    HourlyPageBudget,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfluencePage:
    id: str
    title: str
    space_key: str
    web_url: str
    storage_html: str
    version_when: str  # ISO timestamp


class ConfluenceConnector(BaseConnector):
    """Ingest Confluence pages for one space into the KB review queue."""

    connector_name: ClassVar[str] = "confluence"

    _BACKOFF_SECONDS: tuple[int, ...] = (60, 300, 1800)  # 1m, 5m, 30m
    _PAGE_LIMIT: int = 50

    def __init__(
        self,
        *,
        db: Any,
        base_url: str,
        credentials_ref: str,
        extractor: Any,
        review_queue: Any,
        vault: Any,
        budget: HourlyPageBudget | None = None,
        session: aiohttp.ClientSession | None = None,
        audit_log: Any | None = None,
    ) -> None:
        super().__init__(db)
        self._base_url = base_url.rstrip("/")
        self._credentials_ref = credentials_ref
        self._extractor = extractor
        self._review_queue = review_queue
        self._vault = vault
        self._budget = budget or HourlyPageBudget()
        self._session_override = session
        self._audit_log = audit_log

    # ── Credential handling ───────────────────────────────────────────

    async def _build_auth_header(self) -> str:
        raw = await self._vault.retrieve(self._credentials_ref)
        if not raw:
            raise RuntimeError(
                f"Confluence credential not in vault: {self._credentials_ref}"
            )
        # Stored format: "email:api_token"
        encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
        return f"Basic {encoded}"

    # ── HTTP / pagination ─────────────────────────────────────────────

    def _acquire_session(self) -> aiohttp.ClientSession:
        if self._session_override is not None:
            return self._session_override
        return aiohttp.ClientSession()

    async def _release_session(self, session: aiohttp.ClientSession) -> None:
        # Only close sessions we created ourselves.
        if self._session_override is None:
            await session.close()

    async def _get_with_retry(
        self,
        session: aiohttp.ClientSession,
        url: str,
        params: dict | None,
        auth: str,
    ):
        """GET with Retry-After + exponential backoff on 429/5xx."""
        backoffs = list(self._BACKOFF_SECONDS)
        while True:
            async with session.get(
                url, params=params, headers={"Authorization": auth}
            ) as resp:
                if resp.status == 429:
                    retry_after = int(resp.headers.get("Retry-After", "0"))
                    wait = retry_after if retry_after > 0 else (
                        backoffs.pop(0) if backoffs else self._BACKOFF_SECONDS[-1]
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

    async def _fetch_pages(
        self,
        space_key: str,
        cursor: str | None,
    ):
        """Async generator yielding ``ConfluencePage`` objects."""
        auth = await self._build_auth_header()
        session = self._acquire_session()
        try:
            params: dict[str, Any] = {
                "spaceKey": space_key,
                "expand": "body.storage,version",
                "limit": self._PAGE_LIMIT,
            }
            if cursor:
                params["updated-since"] = cursor
            url = f"{self._base_url}/rest/api/content"

            while True:
                payload = await self._get_with_retry(session, url, params, auth)
                for raw in payload.get("results", []):
                    yield self._to_page(raw)
                next_path = (payload.get("_links") or {}).get("next")
                if not next_path:
                    return
                # Atlassian returns relative path; drop query from base
                url = f"{self._base_url}{next_path}"
                params = None  # Next URL already includes the query string.
        finally:
            await self._release_session(session)

    @staticmethod
    def _to_page(raw: dict) -> ConfluencePage:
        webui = ((raw.get("_links") or {}).get("webui")) or ""
        return ConfluencePage(
            id=str(raw["id"]),
            title=raw.get("title", ""),
            space_key=(raw.get("space") or {}).get("key", ""),
            web_url=webui,
            storage_html=((raw.get("body") or {}).get("storage") or {}).get("value", ""),
            version_when=(raw.get("version") or {}).get("when", ""),
        )

    # ── To be implemented in later tasks ──────────────────────────────

    async def _do_sync(
        self,
        project_id: uuid.UUID,
        scope_key: str,
        cursor: str | None,
    ) -> SyncResult:
        raise NotImplementedError("Implemented in a later task")
