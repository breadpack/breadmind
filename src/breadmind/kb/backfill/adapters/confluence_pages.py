"""Page mapping helpers for the Confluence backfill adapter (D3, D6)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from breadmind.kb.backfill.base import BackfillItem
from breadmind.kb.connectors.confluence import html_to_markdown


def page_to_item(raw: dict, base_url: str, source_kind: str) -> BackfillItem:
    """Map a raw Confluence page payload to a :class:`BackfillItem`."""
    page_id = str(raw["id"])
    title = raw.get("title", "")
    space_key = (raw.get("space") or {}).get("key", "")
    webui = ((raw.get("_links") or {}).get("webui")) or ""
    source_uri = (
        f"{base_url}{webui}" if webui.startswith("/") else webui
    )

    # D6: both timestamps
    version_when_str = (raw.get("version") or {}).get("when", "")
    created_date_str = (raw.get("history") or {}).get("createdDate", "")
    source_updated_at = parse_iso(version_when_str)
    source_created_at = parse_iso(created_date_str)

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
        source_kind=source_kind,
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


def parse_iso(iso_str: str) -> datetime:
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
