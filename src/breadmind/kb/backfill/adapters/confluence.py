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
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from collections.abc import AsyncIterator, Callable, Awaitable
from datetime import datetime, timezone
from typing import Any, ClassVar

import aiohttp

from breadmind.kb.backfill.base import BackfillItem, BackfillJob
from breadmind.kb.connectors.confluence import (
    ConfluenceConnector,
    html_to_markdown,
)

logger = logging.getLogger(__name__)

# Reuse connector constants without modifying the connector.
_PAGE_LIMIT: int = ConfluenceConnector._PAGE_LIMIT
_BACKOFF_SECONDS: tuple[int, ...] = ConfluenceConnector._BACKOFF_SECONDS
_CHUNK_CHAR_BUDGET: int = ConfluenceConnector._CHUNK_CHAR_BUDGET

_EXPAND = (
    "body.storage,version,history,metadata.labels,"
    "restrictions.read,ancestors,space"
)


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

    # ── CQL builder (D4) ─────────────────────────────────────────────────

    def _build_cql(
        self,
        source_filter: dict[str, Any],
        since: datetime,
        until: datetime,
    ) -> str | None:
        """Build a CQL string for ``discover()``.

        Returns ``None`` for ``kind=page_ids`` (direct fetch, no CQL).
        """
        kind = source_filter.get("kind", "space")
        if kind == "page_ids":
            return None

        since_iso = since.strftime("%Y-%m-%dT%H:%M:%S")
        until_iso = until.strftime("%Y-%m-%dT%H:%M:%S")
        time_clause = (
            f'lastModified >= "{since_iso}" AND lastModified < "{until_iso}"'
        )

        if kind == "space":
            spaces = source_filter.get("spaces", [])
            space_list = ",".join(f'"{s}"' for s in spaces)
            cql = (
                f"space in ({space_list}) AND type=page AND status=current"
                f" AND {time_clause}"
            )
            labels_exclude = source_filter.get("labels_exclude") or []
            if labels_exclude:
                lbl = ",".join(f'"{lbl_name}"' for lbl_name in labels_exclude)
                cql += f' AND label NOT IN ({lbl})'
            return cql

        if kind == "subtree":
            root_id = source_filter.get("root_page_id", "")
            return (
                f'ancestor = "{root_id}" AND type=page AND status=current'
                f" AND {time_clause}"
            )

        raise ValueError(f"Unknown source_filter.kind: {kind!r}")

    def _build_cql_with_resume(
        self,
        source_filter: dict[str, Any],
        since: datetime,
        until: datetime,
        resume_cursor: str,
    ) -> str:
        """Append a resume clause to a base CQL string (D2/Task 10)."""
        base = self._build_cql(source_filter, since, until) or ""
        # cursor format: "<ms>:<page_id>"
        parts = resume_cursor.split(":", 1)
        ts_ms = int(parts[0])
        page_id = parts[1] if len(parts) > 1 else ""
        resume_dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        iso = resume_dt.strftime("%Y-%m-%dT%H:%M:%S")
        resume_clause = (
            f'(lastModified > "{iso}" '
            f'OR (lastModified = "{iso}" AND id > "{page_id}"))'
        )
        if base:
            return f"{base} AND {resume_clause}"
        return resume_clause

    # ── Auth / HTTP helpers ───────────────────────────────────────────────

    async def _build_auth_header(self) -> str:
        raw = await self._vault.retrieve(self._credentials_ref)
        if not raw:
            raise RuntimeError(
                f"Confluence credential not in vault: {self._credentials_ref}"
            )
        encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
        return f"Basic {encoded}"

    def _acquire_session(self) -> aiohttp.ClientSession:
        if self._session_override is not None:
            return self._session_override
        return aiohttp.ClientSession()

    async def _release_session(self, session: aiohttp.ClientSession) -> None:
        if self._session_override is None:
            await session.close()

    async def _get_with_retry(
        self,
        session: aiohttp.ClientSession,
        url: str,
        params: dict | None,
        auth: str,
    ) -> dict:
        """GET with Retry-After + exponential back-off on 429/5xx.

        Intentionally re-implemented (not imported from ConfluenceConnector)
        so this adapter has zero coupling to the incremental connector
        instance state (plan self-review note 7).
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

    async def _fetch_page_by_id(
        self,
        session: aiohttp.ClientSession,
        page_id: str,
        auth: str,
    ) -> dict:
        url = f"{self._base_url}/rest/api/content/{page_id}"
        return await self._get_with_retry(
            session, url, {"expand": _EXPAND}, auth
        )

    # ── Page → BackfillItem mapping (D3 + D6) ────────────────────────────

    def _page_to_item(self, raw: dict) -> BackfillItem:
        """Map a raw Confluence page payload to a :class:`BackfillItem`."""
        page_id = str(raw["id"])
        title = raw.get("title", "")
        space_key = (raw.get("space") or {}).get("key", "")
        webui = ((raw.get("_links") or {}).get("webui")) or ""
        source_uri = (
            f"{self._base_url}{webui}" if webui.startswith("/") else webui
        )

        # D6: both timestamps
        version_when_str = (raw.get("version") or {}).get("when", "")
        created_date_str = (raw.get("history") or {}).get("createdDate", "")
        source_updated_at = _parse_iso(version_when_str)
        source_created_at = _parse_iso(created_date_str)

        # D3: parent_ref = last ancestor
        ancestors = raw.get("ancestors") or []
        parent_ref: str | None = None
        if ancestors:
            parent_ref = f"confluence_page:{ancestors[-1]['id']}"

        # author (Cloud uses accountId)
        history = raw.get("history") or {}
        created_by = history.get("createdBy") or {}
        author = created_by.get("accountId") or None

        # body: storage-format HTML → markdown (Q-CF-3: storage retained)
        body_html = (
            (raw.get("body") or {})
            .get("storage", {})
            .get("value", "")
        )
        body = html_to_markdown(body_html)

        # labels
        labels = [
            r["name"]
            for r in (
                ((raw.get("metadata") or {})
                 .get("labels") or {})
                .get("results", [])
            )
        ]

        # restrictions
        read_restrictions = (
            (raw.get("restrictions") or {})
            .get("read", {})
            .get("restrictions", {})
        )
        restriction_users = [
            u.get("accountId", u.get("username", ""))
            for u in read_restrictions.get("user", [])
        ]
        restriction_groups = [
            g.get("name", "")
            for g in read_restrictions.get("group", [])
        ]

        page_status = raw.get("status", "current")
        space_status = (raw.get("space") or {}).get("status", "current")
        has_attachments = bool((raw.get("children") or {}).get("attachment"))

        extra: dict[str, Any] = {
            "space_key": space_key,
            "labels": labels,
            "restrictions": {
                "users": restriction_users,
                "groups": restriction_groups,
            },
            "status": page_status,
            "space_status": space_status,
            "has_attachments": has_attachments,
            "page_metadata": raw.get("metadata") or {},
            "_extracted_from": "confluence_backfill",
        }

        return BackfillItem(
            source_kind=self.source_kind,
            source_native_id=page_id,
            source_uri=source_uri,
            source_created_at=source_created_at,
            source_updated_at=source_updated_at,
            title=title,
            body=body,
            author=author,
            parent_ref=parent_ref,
            extra=extra,
        )

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
        """Apply signal filters and ACL check; return True to keep the item.

        Checks in order (cheap first):
        1. archived space / page
        2. draft status
        3. attachment-only (empty body + has_attachments)
        4. empty page (body < 50 chars)
        5. ACL restrictions (intersection with membership snapshot)
        """
        extra = item.extra

        # 1. archived
        if (extra.get("space_status") == "archived"
                or (extra.get("page_metadata") or {}).get("archived") is True):
            extra["_skip_reason"] = "archived"
            return False

        # 2. draft
        if extra.get("status", "current") != "current":
            extra["_skip_reason"] = "draft"
            return False

        # 3. attachment-only
        if extra.get("has_attachments") and not item.body.strip():
            extra["_skip_reason"] = "attachment_only"
            return False

        # 4. empty page
        if len(item.body.strip()) < 50:
            extra["_skip_reason"] = "empty_page"
            return False

        # 5. ACL
        restrictions = extra.get("restrictions") or {}
        r_users: list[str] = restrictions.get("users") or []
        r_groups: list[str] = restrictions.get("groups") or []
        if r_users or r_groups:
            M = self._membership_snapshot or frozenset()
            page_allowed = set(r_users)  # group resolution out-of-scope (Q-CF-5)
            if M.isdisjoint(page_allowed):
                extra["_skip_reason"] = "acl_lock"
                return False
            space_key = extra.get("space_key", "")
            extra["_acl_mark"] = "RESTRICTED"
            extra["_source_channel"] = f"confluence:{space_key}:restricted"
            return True

        space_key = extra.get("space_key", "")
        extra["_acl_mark"] = "PUBLIC"
        extra["_source_channel"] = f"confluence:{space_key}"
        return True

    # ── cursor_of (D2) ───────────────────────────────────────────────────

    def cursor_of(self, item: BackfillItem) -> str:
        """Return ``"<ms_since_epoch>:<page_id>"`` cursor (D2)."""
        ts_ms = int(item.source_updated_at.timestamp() * 1000)
        return f"{ts_ms}:{item.source_native_id}"


# ── Helpers ──────────────────────────────────────────────────────────────

def _parse_iso(iso_str: str) -> datetime:
    """Parse Confluence ISO 8601 timestamp to tz-aware datetime (UTC)."""
    if not iso_str:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    # Normalise trailing Z / milliseconds
    s = iso_str.replace("Z", "+00:00")
    # Strip milliseconds: "2025-06-01T12:00:00.000+00:00" → "2025-06-01T12:00:00+00:00"
    if "." in s:
        dot_idx = s.index(".")
        plus_idx = s.find("+", dot_idx)
        if plus_idx == -1:
            s = s[:dot_idx]
        else:
            s = s[:dot_idx] + s[plus_idx:]
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
