"""Confluence backfill adapter.

Implements :class:`breadmind.kb.backfill.base.BackfillJob` for Confluence
Cloud / Server pages.  Designed as a **separate class** from
:class:`breadmind.kb.connectors.confluence.ConfluenceConnector` so the
existing incremental sync path is never affected (spec §11 C2).

Reused from the connector (import-only, no modification):
- :func:`breadmind.kb.connectors.confluence.html_to_markdown`
- :data:`breadmind.kb.connectors.confluence.ConfluenceConnector._PAGE_LIMIT`
- :data:`breadmind.kb.connectors.confluence.ConfluenceConnector._BACKOFF_SECONDS`
- :data:`breadmind.kb.connectors.confluence.ConfluenceConnector._CHUNK_CHAR_BUDGET`
- :meth:`breadmind.kb.connectors.confluence.ConfluenceConnector._chunk_markdown`

``_get_with_retry`` and ``_build_auth_header`` are re-implemented inline
(intent: zero coupling to ConfluenceConnector's instance state — spec §7,
plan self-review note 7).

Sub-modules
-----------
- :mod:`.confluence_http`    — HTTP session / retry helpers + shared constants
- :mod:`.confluence_cql`     — CQL builder (space / subtree / resume cursor)
- :mod:`.confluence_pages`   — Raw page dict → :class:`BackfillItem` mapper
- :mod:`.confluence_filter`  — D1 signal filter + D2 cursor helper
"""
from __future__ import annotations

import hashlib
import logging
from collections.abc import AsyncIterator, Callable, Awaitable
from typing import Any, ClassVar

import aiohttp

from breadmind.kb.backfill.base import BackfillItem, BackfillJob
from breadmind.kb.backfill.adapters.confluence_cql import (
    build_cql,
    build_cql_with_resume,
)
from breadmind.kb.backfill.adapters.confluence_filter import (
    apply_filter,
    cursor_of as _cursor_of_fn,
)
from breadmind.kb.backfill.adapters.confluence_http import (
    _PAGE_LIMIT,
    _EXPAND,
    acquire_session,
    build_auth_header,
    fetch_page_by_id,
    get_with_retry,
    release_session,
)
from breadmind.kb.backfill.adapters.confluence_pages import page_to_item

logger = logging.getLogger(__name__)


class ConfluenceBackfillAdapter(BackfillJob):
    """Backfill adapter for Confluence Cloud / Server.

    This class implements the :class:`~breadmind.kb.backfill.base.BackfillJob`
    ABC. It is entirely separate from :class:`~breadmind.kb.connectors
    .confluence.ConfluenceConnector` (incremental path).

    Parameters
    ----------
    base_url:
        Confluence root URL, e.g. ``https://myorg.atlassian.net/wiki``
        (Cloud) or ``https://confluence.acme.internal`` (Server / DC).
    credentials_ref:
        Vault key for ``email:api_token`` credentials.
    vault:
        Async secret store; must have ``retrieve(ref) -> str``.
    db:
        Async DB client with ``fetch(sql, *args)`` and ``execute(sql, *args)``.
    http_session:
        Optional :class:`aiohttp.ClientSession` override (for tests).
    budget:
        Optional :class:`~breadmind.kb.connectors.rate_limit.HourlyPageBudget`
        override.
    member_resolver:
        ``async (org_id: UUID) -> frozenset[str]`` — resolves active member
        account IDs for the org (Q-CF-5: plug-in, not hard-wired).
    """

    source_kind: ClassVar[str] = "confluence_page"

    def __init__(
        self,
        *,
        base_url: str,
        credentials_ref: str,
        vault: Any,
        db: Any,
        http_session: aiohttp.ClientSession | None = None,
        budget: Any | None = None,
        member_resolver: Callable[[Any], Awaitable[frozenset[str]]] | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(**kw)
        if not base_url.lower().startswith("https://"):
            raise ValueError("base_url must use https://")
        self._base_url = base_url.rstrip("/")
        self._credentials_ref = credentials_ref
        self._vault = vault
        self._db = db
        self._session_override = http_session
        self._budget = budget
        self._member_resolver: Callable[[Any], Awaitable[frozenset[str]]] = (
            member_resolver or self._default_member_resolver
        )

        # State populated by prepare()
        self._membership_snapshot: frozenset[str] | None = None
        self._instance_id: str | None = None

        # Optional resume cursor (set by CLI dispatcher before discover())
        self._resume_cursor: str | None = None
        # --reingest flag: skip dedup check when True
        self._reingest: bool = False

    # ── instance_id_of (D5) ──────────────────────────────────────────────

    def instance_id_of(self, source_filter: dict[str, Any]) -> str:  # noqa: ARG002
        """Return a 16-hex SHA-256 digest of the base URL (D5).

        This ensures cloud and on-prem instances of the same org get
        independent :class:`~breadmind.kb.connectors.rate_limit.HourlyPageBudget`
        dimensions.
        """
        return hashlib.sha256(self._base_url.encode()).hexdigest()[:16]

    # ── prepare() (C1) ──────────────────────────────────────────────────

    async def prepare(self) -> None:
        """Snapshot active membership and resolve instance_id (idempotent)."""
        if self._membership_snapshot is not None:
            return
        self._membership_snapshot = await self._member_resolver(self.org_id)
        self._instance_id = self.instance_id_of(self.source_filter)

    @staticmethod
    async def _default_member_resolver(org_id: Any) -> frozenset[str]:  # noqa: ARG004
        """Fallback resolver — returns empty set (no ACL drops)."""
        return frozenset()

    # ── CQL delegation ───────────────────────────────────────────────────

    def _build_cql(self, source_filter: dict[str, Any], since: Any, until: Any) -> str | None:
        return build_cql(source_filter, since, until)

    def _build_cql_with_resume(
        self,
        source_filter: dict[str, Any],
        since: Any,
        until: Any,
        resume_cursor: str,
    ) -> str:
        return build_cql_with_resume(source_filter, since, until, resume_cursor)

    # ── Auth / HTTP helpers ───────────────────────────────────────────────

    async def _build_auth_header(self) -> str:
        return await build_auth_header(self._vault, self._credentials_ref)

    def _acquire_session(self) -> aiohttp.ClientSession:
        return acquire_session(self._session_override)

    async def _release_session(self, session: aiohttp.ClientSession) -> None:
        await release_session(session, self._session_override)

    async def _get_with_retry(
        self,
        session: aiohttp.ClientSession,
        url: str,
        params: dict | None,
        auth: str,
    ) -> dict:
        return await get_with_retry(session, url, params, auth)

    async def _fetch_page_by_id(
        self,
        session: aiohttp.ClientSession,
        page_id: str,
        auth: str,
    ) -> dict:
        return await fetch_page_by_id(session, self._base_url, page_id, auth)

    # ── Page → BackfillItem mapping (D3 + D6) ────────────────────────────

    def _page_to_item(self, raw: dict) -> BackfillItem:
        """Map a raw Confluence page payload to a :class:`BackfillItem`."""
        return page_to_item(raw, self._base_url, self.source_kind)

    # ── discover() ──────────────────────────────────────────────────────

    async def discover(self) -> AsyncIterator[BackfillItem]:
        """Yield :class:`BackfillItem` objects for all matching pages.

        Handles:
        - ``kind=space`` / ``kind=subtree`` → CQL search endpoint + pagination
        - ``kind=page_ids`` → direct per-id fetch + client-side window cut
        - Dedup prefetch (single IN-list query) at start of discover
        - Resume cursor injection (``_resume_cursor``)
        """
        auth = await self._build_auth_header()
        session = self._acquire_session()
        try:
            kind = self.source_filter.get("kind", "space")
            if kind == "page_ids":
                async for item in self._discover_page_ids(session, auth):
                    yield item
            else:
                async for item in self._discover_cql(session, auth):
                    yield item
        finally:
            await self._release_session(session)

    async def _discover_cql(
        self,
        session: aiohttp.ClientSession,
        auth: str,
    ) -> AsyncIterator[BackfillItem]:
        """Paginate via CQL search and yield items (with dedup tagging)."""
        # Build CQL (with optional resume)
        if self._resume_cursor:
            cql = self._build_cql_with_resume(
                self.source_filter, self.since, self.until, self._resume_cursor
            )
        else:
            cql = self._build_cql(self.source_filter, self.since, self.until)

        url = f"{self._base_url}/rest/api/content/search"
        params: dict[str, Any] | None = {
            "cql": cql,
            "expand": _EXPAND,
            "limit": _PAGE_LIMIT,
        }

        # Collect page IDs first pass for dedup prefetch (single query)
        raw_pages: list[dict] = []
        first_url = url
        first_params = params
        tmp_url = first_url
        tmp_params: dict | None = first_params
        while True:
            payload = await self._get_with_retry(session, tmp_url, tmp_params, auth)
            for raw in payload.get("results", []):
                raw_pages.append(raw)
            next_path = (payload.get("_links") or {}).get("next")
            if not next_path:
                break
            tmp_url = f"{self._base_url}{next_path}"
            tmp_params = None

        # Dedup: prefetch already-ingested IDs in one IN-list query
        ingested_ids = await self._prefetch_ingested(
            [str(p["id"]) for p in raw_pages]
        )

        for raw in raw_pages:
            item = self._page_to_item(raw)
            if not self._reingest and item.source_native_id in ingested_ids:
                # Tag for runner to count as skipped_existing
                item.extra["_skip_reason"] = "skipped_existing"
            yield item

    async def _discover_page_ids(
        self,
        session: aiohttp.ClientSession,
        auth: str,
    ) -> AsyncIterator[BackfillItem]:
        """Fetch pages by explicit ID list with client-side window cut (D4)."""
        ids = self.source_filter.get("ids", [])
        ingested_ids = await self._prefetch_ingested(list(ids))

        for page_id in ids:
            try:
                raw = await self._fetch_page_by_id(session, str(page_id), auth)
            except Exception:
                logger.exception("Failed to fetch page %s", page_id)
                continue

            item = self._page_to_item(raw)
            # Client-side time window cut (D4 fallback)
            if not (self.since <= item.source_updated_at < self.until):
                continue
            if not self._reingest and item.source_native_id in ingested_ids:
                item.extra["_skip_reason"] = "skipped_existing"
            yield item

    async def _prefetch_ingested(self, page_ids: list[str]) -> set[str]:
        """Return the set of page IDs already in org_knowledge (dedup, Task 11)."""
        if not page_ids:
            return set()
        try:
            rows = await self._db.fetch(
                "SELECT source_native_id "
                "FROM org_knowledge "
                "WHERE project_id=$1 "
                "  AND source_kind='confluence_page' "
                "  AND source_native_id = ANY($2)",
                self.org_id,
                page_ids,
            )
            return {r["source_native_id"] for r in rows}
        except Exception:
            logger.exception("Failed to prefetch ingested IDs; proceeding without dedup")
            return set()

    # ── filter() (D1 keys) ──────────────────────────────────────────────

    def filter(self, item: BackfillItem) -> bool:
        """Apply signal filters and ACL check; return True to keep the item."""
        return apply_filter(item, self._membership_snapshot)

    # ── cursor_of (D2) ───────────────────────────────────────────────────

    def cursor_of(self, item: BackfillItem) -> str:
        """Return ``"<ms_since_epoch>:<page_id>"`` cursor (D2)."""
        return _cursor_of_fn(item)


# ── Public helper re-export (backward compat for any direct callers) ─────

def _parse_iso(iso_str: str):  # noqa: ANN001, ANN202
    """Parse Confluence ISO 8601 timestamp (kept for backward compat)."""
    from breadmind.kb.backfill.adapters.confluence_pages import parse_iso
    return parse_iso(iso_str)
