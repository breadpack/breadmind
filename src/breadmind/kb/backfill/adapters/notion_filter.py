"""Signal filter for Notion backfill items (§4).

Implements the 10-key signal filter evaluation order from the spec:
archived → in_trash → template → acl_lock → share_revoked →
title_only → empty_page → oversized → duplicate_body → redact_dropped
"""
from __future__ import annotations

import hashlib
import logging
import uuid

from breadmind.kb.backfill.base import BackfillItem

_log = logging.getLogger(__name__)

# Signal filter thresholds (§4).
_EMPTY_PAGE_MIN_CHARS = 120
_OVERSIZED_MAX_CHARS = 200_000


def apply_filter(
    item: BackfillItem,
    *,
    org_id: uuid.UUID,
    share_in_snapshot: frozenset[str],
    seen_body_hashes: set[str],
) -> bool:
    """Apply §4 signal filter rules in spec-defined order.

    Returns True if item should be ingested; False if it should be dropped.
    Sets item.extra["_skip_reason"] when dropping.

    Args:
        item: The BackfillItem to evaluate.
        org_id: Organisation UUID (used for duplicate_body key scoping).
        share_in_snapshot: Frozenset of visible page IDs from prepare().
        seen_body_hashes: Mutable set of body-hash keys seen in this run.

    Rule evaluation order (spec §4):
    archived → in_trash → template → acl_lock → share_revoked →
    title_only → empty_page → oversized → duplicate_body → redact_dropped
    """
    extra = item.extra

    # Already marked by discover() (e.g. share_revoked from 404)
    if extra.get("_skip_reason"):
        return False

    # 1. archived
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
        share_in_snapshot
        and item.source_native_id not in share_in_snapshot
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
    key = f"{org_id}:{item.title}:{body_hash}"
    if key in seen_body_hashes:
        extra["_skip_reason"] = "duplicate_body"
        return False
    seen_body_hashes.add(key)

    # 10. redact_dropped — runner handles; adapter just registers the key
    # (no evaluation here per spec §4 note)

    return True
