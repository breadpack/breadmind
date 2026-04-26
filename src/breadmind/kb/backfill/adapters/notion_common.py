"""Shared Notion API constants and helpers.

Extracted from personal/adapters/notion.py so both the personal adapter
(task-sync) and the org KB backfill adapter can import without duplication.

Spec: docs/superpowers/specs/2026-04-26-backfill-notion-design.md §9
"""
from __future__ import annotations

from datetime import datetime

BASE_URL: str = "https://api.notion.com/v1"
NOTION_VERSION: str = "2022-06-28"


def build_headers(api_key: str) -> dict[str, str]:
    """Return the standard Notion API request headers.

    All three keys are required by the Notion API:
    - Authorization: Bearer <token>
    - Notion-Version: API version pin
    - Content-Type: for JSON request bodies
    """
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def parse_iso(value: str | None) -> datetime | None:
    """Parse a Notion ISO 8601 timestamp string into an aware datetime.

    Notion returns timestamps with a trailing ``Z`` which Python's
    ``fromisoformat`` does not accept before 3.11. We normalise ``Z`` to
    ``+00:00`` for compatibility across Python 3.12+ as well.

    Returns ``None`` when *value* is ``None`` (e.g. optional timestamp fields).
    """
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
