"""Database handling for Notion backfill (§3.3).

Contains DB row collapse + DB-level index page generation (Task 6):
- _emit_database(): yields DB index page + all rows for a database object
- _emit_database_rows(): paginates databases.query and yields row BackfillItems
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

import aiohttp

from breadmind.kb.backfill.base import BackfillItem
from breadmind.kb.backfill.adapters.notion_common import parse_iso
from breadmind.kb.backfill.adapters.notion_blocks import (
    _extract_rich_text,
    _extract_title,
    _make_parent_ref,
    _flatten_blocks,
)

if TYPE_CHECKING:
    from breadmind.kb.backfill.adapters.notion_client import NotionClient

_log = logging.getLogger(__name__)


async def emit_database(
    db_obj: dict[str, Any],
    *,
    client: "NotionClient",
    source_kind: str,
    since: datetime,
    until: datetime,
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
    if updated_at < since or updated_at >= until:
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
    async for item in emit_database_rows(
        db_id,
        parent_ref=f"notion_database:{db_id}",
        client=client,
        source_kind=source_kind,
    ):
        yield item


async def emit_database_rows(
    db_id: str,
    *,
    parent_ref: str | None,
    client: "NotionClient",
    source_kind: str,
) -> AsyncIterator[BackfillItem]:
    """Paginate databases.query and yield each row as a BackfillItem."""
    cursor: str | None = None
    while True:
        resp = await client.query_database(db_id, start_cursor=cursor)
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
                    client, row_id, db_queue=None
                )
            except aiohttp.ClientResponseError as exc:
                if exc.status == 404:
                    yield BackfillItem(
                        source_kind=source_kind,
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
                    source_kind=source_kind,
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
                    source_kind=source_kind,
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
                source_kind=source_kind,
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
