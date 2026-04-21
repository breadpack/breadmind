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

    # ── To be implemented in later tasks ──────────────────────────────

    async def _do_sync(
        self,
        project_id: uuid.UUID,
        scope_key: str,
        cursor: str | None,
    ) -> SyncResult:
        raise NotImplementedError("Implemented in a later task")
