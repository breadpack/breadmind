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

import hashlib
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import aiohttp

from breadmind.kb.backfill.base import BackfillItem, BackfillJob
from breadmind.kb.backfill.adapters.notion_common import parse_iso
from breadmind.kb.backfill.adapters.notion_client import NotionClient

_log = logging.getLogger(__name__)

# Block tree depth cap (§3.2).
_MAX_DEPTH = 8
_DEPTH_TRUNCATION_MARKER = "... [content truncated at depth limit]"

# Signal filter thresholds (§4).
_EMPTY_PAGE_MIN_CHARS = 120
_OVERSIZED_MAX_CHARS = 200_000


def _extract_rich_text(rich_text_list: list[dict[str, Any]]) -> str:
    """Join plain_text from a Notion rich_text array."""
    return "".join(t.get("plain_text", "") for t in rich_text_list)


def _extract_title(page: dict[str, Any]) -> str:
    """Extract plain-text title from a page or database object."""
    props = page.get("properties", {})
    for key in ("title", "Title", "Name"):
        prop = props.get(key)
        if prop and prop.get("type") == "title":
            return _extract_rich_text(prop.get("title", []))
        if prop and prop.get("title"):
            return _extract_rich_text(prop["title"])
    # Database objects expose title at top level
    top_title = page.get("title")
    if isinstance(top_title, list):
        return _extract_rich_text(top_title)
    return "(untitled)"


def _make_parent_ref(parent: dict[str, Any]) -> str | None:
    """Build parent_ref from a Notion page/block parent descriptor (D3)."""
    ptype = parent.get("type")
    if ptype == "workspace":
        return None
    if ptype == "page_id":
        return f"notion_page:{parent['page_id']}"
    if ptype == "database_id":
        return f"notion_database:{parent['database_id']}"
    return None


# ---------------------------------------------------------------------------
# Block-tree → markdown flattener
# ---------------------------------------------------------------------------


async def _flatten_blocks(
    client: NotionClient,
    root_block_id: str,
    depth: int = 0,
    *,
    db_queue: list[str] | None = None,
) -> str:
    """Recursively fetch block children and render to markdown.

    Args:
        client: Notion API client.
        root_block_id: Block or page ID whose children to flatten.
        depth: Current recursion depth (0 = top level).
        db_queue: Mutable list to append child_database IDs for later queuing.

    Returns:
        Markdown string representation of the block tree.
    """
    if depth >= _MAX_DEPTH:
        return _DEPTH_TRUNCATION_MARKER + "\n"

    lines: list[str] = []
    start_cursor: str | None = None

    while True:
        resp = await client.list_block_children(root_block_id, start_cursor=start_cursor)
        for block in resp.get("results", []):
            text = await _render_block(client, block, depth, db_queue=db_queue)
            if text:
                lines.append(text)
        if not resp.get("has_more"):
            break
        start_cursor = resp.get("next_cursor")

    return "\n".join(lines)


async def _render_block(
    client: NotionClient,
    block: dict[str, Any],
    depth: int,
    *,
    db_queue: list[str] | None = None,
) -> str:
    """Render a single block to markdown text (§3.2 table)."""
    btype = block.get("type", "")
    data = block.get(btype, {})
    indent = "  " * depth

    # Rich-text types
    if btype == "paragraph":
        return indent + _extract_rich_text(data.get("rich_text", []))
    if btype == "quote":
        text = _extract_rich_text(data.get("rich_text", []))
        return indent + f"> {text}"
    if btype == "callout":
        text = _extract_rich_text(data.get("rich_text", []))
        icon = data.get("icon", {}).get("emoji", "")
        return indent + f"{icon} {text}".strip()
    if btype in ("heading_1", "heading_2", "heading_3"):
        level = int(btype[-1])
        text = _extract_rich_text(data.get("rich_text", []))
        return indent + "#" * level + " " + text
    if btype == "bulleted_list_item":
        text = _extract_rich_text(data.get("rich_text", []))
        children_text = ""
        if block.get("has_children") and depth < _MAX_DEPTH:
            children_text = "\n" + await _flatten_blocks(
                client, block["id"], depth + 1, db_queue=db_queue
            )
        return indent + f"- {text}" + children_text
    if btype == "numbered_list_item":
        text = _extract_rich_text(data.get("rich_text", []))
        children_text = ""
        if block.get("has_children") and depth < _MAX_DEPTH:
            children_text = "\n" + await _flatten_blocks(
                client, block["id"], depth + 1, db_queue=db_queue
            )
        return indent + f"1. {text}" + children_text
    if btype == "to_do":
        checked = data.get("checked", False)
        text = _extract_rich_text(data.get("rich_text", []))
        checkbox = "[x]" if checked else "[ ]"
        return indent + f"- {checkbox} {text}"
    if btype == "code":
        lang = data.get("language", "")
        text = _extract_rich_text(data.get("rich_text", []))
        return indent + f"```{lang}\n{text}\n```"
    if btype == "toggle":
        summary = _extract_rich_text(data.get("rich_text", []))
        children_text = ""
        if block.get("has_children") and depth < _MAX_DEPTH:
            children_text = "\n" + await _flatten_blocks(
                client, block["id"], depth + 1, db_queue=db_queue
            )
        return indent + summary + children_text
    if btype == "equation":
        expr = data.get("expression", "")
        return indent + f"$${expr}$$"
    if btype == "divider":
        return ""  # drop
    if btype in ("breadcrumb", "table_of_contents"):
        return ""  # drop
    if btype in ("image", "file", "pdf", "video", "audio", "bookmark"):
        # P3 placeholder
        caption = _extract_rich_text(data.get("caption", []))
        name = caption or data.get("name", btype)
        return indent + f"[file: {name}]"
    if btype == "table":
        # Table rows come as children
        if block.get("has_children") and depth < _MAX_DEPTH:
            rows_text = await _flatten_blocks(
                client, block["id"], depth, db_queue=db_queue
            )
            return rows_text
        return ""
    if btype == "table_row":
        cells = data.get("cells", [])
        cell_texts = [_extract_rich_text(cell) for cell in cells]
        return indent + "| " + " | ".join(cell_texts) + " |"
    if btype == "synced_block":
        # Render original only (spec §3.2: mirror is cross-ref only)
        synced_from = data.get("synced_from")
        if synced_from is None:
            # This IS the original
            if block.get("has_children") and depth < _MAX_DEPTH:
                return await _flatten_blocks(
                    client, block["id"], depth, db_queue=db_queue
                )
        return ""  # mirror — skip body
    if btype in ("column_list", "column"):
        # Flatten columns as simple concat (spec §3.2: column info loss OK)
        if block.get("has_children") and depth < _MAX_DEPTH:
            return await _flatten_blocks(
                client, block["id"], depth, db_queue=db_queue
            )
        return ""
    if btype == "child_page":
        # Separate discover entry — do not recurse here (spec §3.2)
        return ""
    if btype == "child_database":
        # Queue for separate DB enumeration (spec §3.2 / Task 6)
        db_id = block.get("id", "")
        if db_queue is not None and db_id:
            db_queue.append(db_id)
        return ""
    # Unknown block types — drop silently
    return ""


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
                    async for item in self._emit_database(obj):
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
            async for item in self._emit_database_rows(db_id, parent_ref=None):
                yield item

    async def _emit_database(
        self, db_obj: dict[str, Any]
    ) -> AsyncIterator[BackfillItem]:
        """Yield a DB index BackfillItem + all row items for a database object."""
        db_id = db_obj["id"]
        title = _extract_title(db_obj)
        updated_at = parse_iso(db_obj.get("last_edited_time"))
        created_at = parse_iso(db_obj.get("created_time"))
        if updated_at is None:
            updated_at = datetime.now(timezone.utc)
        if created_at is None:
            created_at = updated_at

        # D4: since/until cut for DB itself
        if updated_at < self.since or updated_at >= self.until:
            return

        # Build description from top-level description field if present
        desc_parts = db_obj.get("description", [])
        description = _extract_rich_text(desc_parts) if isinstance(desc_parts, list) else ""
        # Properties schema summary
        props = db_obj.get("properties", {})
        prop_summary = ", ".join(props.keys()) if props else ""
        body = f"Database: {title}\n{description}\nProperties: {prop_summary}".strip()

        yield BackfillItem(
            source_kind="notion_database",
            source_native_id=db_id,
            source_uri=db_obj.get("url", ""),
            source_created_at=created_at,
            source_updated_at=updated_at,
            title=f"[DB] {title}",
            body=body,
            author=db_obj.get("created_by", {}).get("id"),
            parent_ref=_make_parent_ref(db_obj.get("parent", {})),
            extra={},
        )

        # Emit rows
        async for item in self._emit_database_rows(db_id, parent_ref=f"notion_database:{db_id}"):
            yield item

    async def _emit_database_rows(
        self, db_id: str, *, parent_ref: str | None
    ) -> AsyncIterator[BackfillItem]:
        """Paginate databases.query and yield each row as a BackfillItem."""
        assert self._client is not None
        cursor: str | None = None
        while True:
            resp = await self._client.query_database(db_id, start_cursor=cursor)
            for row in resp.get("results", []):
                row_id = row["id"]
                updated_at = parse_iso(row.get("last_edited_time"))
                created_at = parse_iso(row.get("created_time"))
                if updated_at is None:
                    continue
                if created_at is None:
                    created_at = updated_at

                title = _extract_title(row)
                row_parent_ref = parent_ref or f"notion_database:{db_id}"
                author = row.get("created_by", {}).get("id")

                try:
                    body = await _flatten_blocks(
                        self._client, row_id, db_queue=None
                    )
                except aiohttp.ClientResponseError as exc:
                    if exc.status == 404:
                        yield BackfillItem(
                            source_kind=self.source_kind,
                            source_native_id=row_id,
                            source_uri=row.get("url", ""),
                            source_created_at=created_at,
                            source_updated_at=updated_at,
                            title=title,
                            body="",
                            author=author,
                            parent_ref=row_parent_ref,
                            extra={"_skip_reason": "share_revoked"},
                        )
                        continue
                    yield BackfillItem(
                        source_kind=self.source_kind,
                        source_native_id=row_id,
                        source_uri=row.get("url", ""),
                        source_created_at=created_at,
                        source_updated_at=updated_at,
                        title=title,
                        body="",
                        author=author,
                        parent_ref=row_parent_ref,
                        extra={"_fetch_error": str(exc)},
                    )
                    continue
                except Exception as exc:
                    yield BackfillItem(
                        source_kind=self.source_kind,
                        source_native_id=row_id,
                        source_uri=row.get("url", ""),
                        source_created_at=created_at,
                        source_updated_at=updated_at,
                        title=title,
                        body="",
                        author=author,
                        parent_ref=row_parent_ref,
                        extra={"_fetch_error": str(exc)},
                    )
                    continue

                yield BackfillItem(
                    source_kind=self.source_kind,
                    source_native_id=row_id,
                    source_uri=row.get("url", ""),
                    source_created_at=created_at,
                    source_updated_at=updated_at,
                    title=title,
                    body=body,
                    author=author,
                    parent_ref=row_parent_ref,
                    extra={},
                )

            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")

    def filter(self, item: BackfillItem) -> bool:
        """Apply §4 signal filter rules in spec-defined order.

        Returns True if item should be ingested; False if it should be dropped.
        Sets item.extra["_skip_reason"] when dropping.

        Rule evaluation order (spec §4):
        archived → in_trash → template → acl_lock → share_revoked →
        title_only → empty_page → oversized → duplicate_body → redact_dropped
        """
        extra = item.extra

        # Already marked by discover() (e.g. share_revoked from 404)
        if extra.get("_skip_reason"):
            return False

        # 1. archived
        # (BackfillItem doesn't carry raw page; we pass page flags via extra)
        if extra.get("archived"):
            extra["_skip_reason"] = "archived"
            return False

        # 2. in_trash
        if extra.get("in_trash"):
            extra["_skip_reason"] = "in_trash"
            return False

        # 3. template
        if extra.get("template") or item.title.startswith("Template:"):
            extra["_skip_reason"] = "template"
            return False

        # 4. acl_lock (page not in share-in snapshot)
        if (
            self._share_in_snapshot
            and item.source_native_id not in self._share_in_snapshot
            and item.source_kind == "notion_page"
        ):
            extra["_skip_reason"] = "acl_lock"
            return False

        # 5. share_revoked — handled above via pre-set _skip_reason

        # 6. title_only (no body blocks)
        if extra.get("_block_count", -1) == 0:
            extra["_skip_reason"] = "title_only"
            return False

        # 7. empty_page
        stripped_body = item.body.strip()
        if len(stripped_body) < _EMPTY_PAGE_MIN_CHARS:
            extra["_skip_reason"] = "empty_page"
            return False

        # 8. oversized
        if len(item.body) > _OVERSIZED_MAX_CHARS:
            _log.warning(
                "notion page %s oversized (%d chars), marking for split audit",
                item.source_native_id,
                len(item.body),
            )
            extra["_skip_reason"] = "oversized"
            return False

        # 9. duplicate_body (in-run hash dedup — cross-run handled by DB UNIQUE)
        body_hash = hashlib.sha256(item.body.encode()).hexdigest()
        key = f"{self.org_id}:{item.title}:{body_hash}"
        if key in self._seen_body_hashes:
            extra["_skip_reason"] = "duplicate_body"
            return False
        self._seen_body_hashes.add(key)

        # 10. redact_dropped — runner handles; adapter just registers the key
        # (no evaluation here per spec §4 note)

        return True

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
