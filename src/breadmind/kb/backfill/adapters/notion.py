"""NotionBackfillAdapter — org KB backfill over Notion pages.

Spec: docs/superpowers/specs/2026-04-26-backfill-notion-design.md
Plan: docs/superpowers/plans/2026-04-26-backfill-notion.md

Architecture:
- Extends BackfillJob ABC (backbone, never modified here).
- discover() uses Notion POST /v1/search (sort desc last_edited_time) with
  client-side since/until cut (D4 — Notion search has no server-side range).
- Block tree is flattened to markdown via _flatten_blocks() (§3.2).
- Database entries emit a meta index page + rows via databases.query (§3.3).
- filter() evaluates §4 signal rules in spec-defined order (sync, no API calls).
- cursor_of() encodes last_edited_time:page_id (D2).
- instance_id_of() returns workspace_id (D5).
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import aiohttp

from breadmind.kb.backfill.base import BackfillItem, BackfillJob
from breadmind.kb.backfill.adapters.notion_common import parse_iso
from breadmind.kb.backfill.adapters.notion_client import NotionClient
from breadmind.kb.backfill.adapters.notion_blocks import (
    _extract_title,
    _make_parent_ref,
    _flatten_blocks,
    _render_block,
    _MAX_DEPTH,
    _DEPTH_TRUNCATION_MARKER,
)
from breadmind.kb.backfill.adapters.notion_database import (
    emit_database,
    emit_database_rows,
)
from breadmind.kb.backfill.adapters.notion_filter import apply_filter

_log = logging.getLogger(__name__)

# Re-export private symbols consumed by tests (import paths must stay stable).
__all__ = [
    "NotionBackfillAdapter",
    "_cursor_to_iso",
    "_flatten_blocks",
    "_render_block",
    "_DEPTH_TRUNCATION_MARKER",
    "_MAX_DEPTH",
]


# ---------------------------------------------------------------------------
# NotionBackfillAdapter
# ---------------------------------------------------------------------------


class NotionBackfillAdapter(BackfillJob):
    """Backfill adapter that ingests Notion pages into org_knowledge.

    Implements BackfillJob ABC:
    - prepare(): fetch users/me for workspace_id + snapshot share-in page set.
    - discover(): search-based page enumeration + block flatten + DB queuing.
    - filter(): sync §4 signal rules in spec order.
    - cursor_of(): encodes last_edited_time:page_id (D2).
    - instance_id_of(): workspace_id (D5).
    """

    source_kind: str = "notion_page"

    def __init__(
        self,
        *,
        org_id: uuid.UUID,
        source_filter: dict[str, Any],
        since: datetime,
        until: datetime,
        dry_run: bool,
        token_budget: int,
        config: dict[str, Any] | None = None,
        client: NotionClient | None = None,
        vault: Any | None = None,
    ) -> None:
        super().__init__(
            org_id=org_id,
            source_filter=source_filter,
            since=since,
            until=until,
            dry_run=dry_run,
            token_budget=token_budget,
            config=config,
        )
        self._client = client
        self._vault = vault
        self._workspace_id: str = ""
        self._share_in_snapshot: frozenset[str] = frozenset()
        # In-run duplicate body hash set (Task 8: same-run dedup only)
        self._seen_body_hashes: set[str] = set()
        # Optional HourlyPageBudget (Task 14: instance-keyed D5)
        self._budget: Any | None = None

    # ------------------------------------------------------------------
    # BackfillJob interface
    # ------------------------------------------------------------------

    async def prepare(self) -> None:
        """Authenticate + snapshot share-in page set.

        1. If no client was injected, retrieve token from vault and build one.
        2. Call GET /users/me to verify auth and get workspace_id.
        3. Paginate POST /search to build _share_in_snapshot.

        Raises PermissionError on 401/403 auth failure.
        """
        if self._client is None:
            token = await self._resolve_token()
            self._client = NotionClient(token=token)

        # Verify auth and get workspace_id.
        try:
            me = await self._client.request("GET", "/users/me")
        except aiohttp.ClientResponseError as exc:
            if exc.status in (401, 403):
                raise PermissionError(
                    f"Notion auth failed (status={exc.status}) for org {self.org_id}"
                ) from exc
            raise

        self._workspace_id = (
            me.get("bot", {}).get("workspace_id", "")
            or me.get("workspace_id", "")
        )

        # Snapshot visible pages.
        page_ids: list[str] = []
        cursor: str | None = None
        while True:
            resp = await self._client.search(
                filter={"value": "page", "property": "object"},
                sort={"timestamp": "last_edited_time", "direction": "descending"},
                start_cursor=cursor,
            )
            for obj in resp.get("results", []):
                if obj.get("object") in ("page", "database"):
                    page_ids.append(obj["id"])
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")

        self._share_in_snapshot = frozenset(page_ids)

    def discover(self) -> AsyncIterator[BackfillItem]:
        """Async generator: yield BackfillItems via Notion search + block flatten."""
        return self._discover_impl()

    async def _discover_impl(self) -> AsyncIterator[BackfillItem]:  # type: ignore[override]
        """Inner async generator implementation."""
        assert self._client is not None, "call prepare() first"

        cursor: str | None = None
        db_queue: list[str] = []  # child_database block IDs to enumerate

        # Resume support: advance since if a resume cursor is set (Task 7).
        effective_since = self.since
        if hasattr(self, "_resume_cursor") and self._resume_cursor:
            from breadmind.kb.backfill.adapters.notion import _cursor_to_iso
            effective_since = max(self.since, _cursor_to_iso(self._resume_cursor))

        # Phase A: search-based enumeration
        while True:
            resp = await self._client.search(
                filter={"value": "page", "property": "object"},
                sort={"timestamp": "last_edited_time", "direction": "descending"},
                start_cursor=cursor,
            )

            stop_search = False
            for obj in resp.get("results", []):
                obj_type = obj.get("object")
                if obj_type == "database":
                    # Emit a DB index page (Task 6)
                    async for item in emit_database(
                        obj,
                        client=self._client,
                        source_kind=self.source_kind,
                        since=self.since,
                        until=self.until,
                    ):
                        yield item
                    continue

                # It's a page object
                updated_at = parse_iso(obj.get("last_edited_time"))
                if updated_at is None:
                    continue

                # D4: client-side since/until cut
                if updated_at < effective_since:
                    stop_search = True
                    break
                if updated_at >= self.until:
                    continue

                page_id = obj["id"]
                created_at = parse_iso(obj.get("created_time"))
                if created_at is None:
                    created_at = updated_at

                title = _extract_title(obj)
                parent_ref = _make_parent_ref(obj.get("parent", {}))
                author = obj.get("created_by", {}).get("id")

                # Fetch + flatten block body
                try:
                    body = await _flatten_blocks(
                        self._client, page_id, db_queue=db_queue
                    )
                except aiohttp.ClientResponseError as exc:
                    if exc.status == 404:
                        _log.info(
                            "notion page %s returned 404 (share revoked)", page_id
                        )
                        yield BackfillItem(
                            source_kind=self.source_kind,
                            source_native_id=page_id,
                            source_uri=obj.get("url", ""),
                            source_created_at=created_at,
                            source_updated_at=updated_at,
                            title=title,
                            body="",
                            author=author,
                            parent_ref=parent_ref,
                            extra={"_skip_reason": "share_revoked"},
                        )
                        continue
                    # Other errors: failure isolation (Task 10)
                    _log.warning(
                        "notion page %s fetch failed: %s", page_id, exc
                    )
                    # Yield a skip so caller can count errors
                    yield BackfillItem(
                        source_kind=self.source_kind,
                        source_native_id=page_id,
                        source_uri=obj.get("url", ""),
                        source_created_at=created_at,
                        source_updated_at=updated_at,
                        title=title,
                        body="",
                        author=author,
                        parent_ref=parent_ref,
                        extra={"_fetch_error": str(exc)},
                    )
                    continue
                except Exception as exc:
                    # Task 10: per-page failure isolation
                    _log.warning(
                        "notion page %s processing failed: %s", page_id, exc
                    )
                    yield BackfillItem(
                        source_kind=self.source_kind,
                        source_native_id=page_id,
                        source_uri=obj.get("url", ""),
                        source_created_at=created_at,
                        source_updated_at=updated_at,
                        title=title,
                        body="",
                        author=author,
                        parent_ref=parent_ref,
                        extra={"_fetch_error": str(exc)},
                    )
                    continue

                # Task 14: per-page budget consume (D5 instance-keyed)
                if self._budget is not None:
                    await self._budget.consume(
                        self.org_id, count=1, instance_id=self._workspace_id
                    )

                yield BackfillItem(
                    source_kind=self.source_kind,
                    source_native_id=page_id,
                    source_uri=obj.get("url", ""),
                    source_created_at=created_at,
                    source_updated_at=updated_at,
                    title=title,
                    body=body,
                    author=author,
                    parent_ref=parent_ref,
                    extra={},
                )

            if stop_search or not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")

        # Phase C: enumerate queued databases (inline child_database blocks)
        for db_id in db_queue:
            async for item in emit_database_rows(
                db_id,
                parent_ref=None,
                client=self._client,
                source_kind=self.source_kind,
            ):
                yield item

    def filter(self, item: BackfillItem) -> bool:
        """Apply §4 signal filter rules in spec-defined order.

        Returns True if item should be ingested; False if it should be dropped.
        Sets item.extra["_skip_reason"] when dropping.
        """
        return apply_filter(
            item,
            org_id=self.org_id,
            share_in_snapshot=self._share_in_snapshot,
            seen_body_hashes=self._seen_body_hashes,
        )

    def cursor_of(self, item: BackfillItem) -> str:
        """Encode cursor as last_edited_time:page_id (D2, opaque to backbone)."""
        return f"{item.source_updated_at.isoformat()}:{item.source_native_id}"

    def instance_id_of(self, source_filter: dict[str, Any]) -> str:
        """Return workspace_id as HourlyPageBudget instance dimension (D5)."""
        return self._workspace_id or source_filter.get("workspace", "")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _resolve_token(self) -> str:
        """Retrieve the Notion integration token from the vault."""
        if self._vault is None:
            raise PermissionError(
                f"No vault configured and no client injected for org {self.org_id}"
            )
        key = f"notion:org:{self.org_id}"
        token = await self._vault.retrieve(key)
        if not token:
            raise PermissionError(
                f"Vault has no Notion token at key {key!r}"
            )
        return token


def _cursor_to_iso(cursor: str) -> datetime:
    """Parse the ISO timestamp prefix from a cursor string (D2).

    Format: ``<ISO8601_datetime>:<page_id>``.
    """
    # The format is: <ISO8601_datetime>:<page_id>
    # ISO+00:00 ends with a numeric offset; page_id has no ':'.
    # Split at the last ':' to recover ISO part.
    parts = cursor.rsplit(":", 1)
    if len(parts) == 2:
        try:
            return datetime.fromisoformat(parts[0])
        except ValueError:
            pass
    return datetime.fromisoformat(cursor)
