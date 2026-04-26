"""Filter and cursor helpers for the Confluence backfill adapter (D1, D2)."""
from __future__ import annotations

from breadmind.kb.backfill.base import BackfillItem


def apply_filter(
    item: BackfillItem,
    membership_snapshot: frozenset[str] | None,
) -> bool:
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
        M = membership_snapshot or frozenset()
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


def cursor_of(item: BackfillItem) -> str:
    """Return ``"<ms_since_epoch>:<page_id>"`` cursor (D2)."""
    ts_ms = int(item.source_updated_at.timestamp() * 1000)
    return f"{ts_ms}:{item.source_native_id}"
