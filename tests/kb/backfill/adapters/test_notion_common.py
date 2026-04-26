"""Unit tests for notion_common helpers (Task 1).

Covers:
- parse_iso: Z → +00:00 conversion, None input pass-through
- build_headers: 3 required keys present + Bearer prefix
- personal adapter regression: NotionAdapter still importable after refactor
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from breadmind.kb.backfill.adapters.notion_common import (
    BASE_URL,
    NOTION_VERSION,
    build_headers,
    parse_iso,
)


def test_parse_iso_z_suffix_becomes_utc():
    dt = parse_iso("2026-03-15T08:30:00Z")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0
    assert dt == datetime(2026, 3, 15, 8, 30, 0, tzinfo=timezone.utc)


def test_parse_iso_offset_format_passthrough():
    dt = parse_iso("2026-03-15T08:30:00+00:00")
    assert dt is not None
    assert dt == datetime(2026, 3, 15, 8, 30, 0, tzinfo=timezone.utc)


def test_parse_iso_none_returns_none():
    assert parse_iso(None) is None


def test_build_headers_has_three_required_keys():
    headers = build_headers("secret_abc123")
    assert "Authorization" in headers
    assert "Notion-Version" in headers
    assert "Content-Type" in headers


def test_build_headers_authorization_has_bearer_prefix():
    headers = build_headers("secret_abc123")
    assert headers["Authorization"].startswith("Bearer ")
    assert headers["Authorization"] == "Bearer secret_abc123"


def test_build_headers_notion_version_matches_constant():
    headers = build_headers("key")
    assert headers["Notion-Version"] == NOTION_VERSION


def test_base_url_value():
    assert BASE_URL == "https://api.notion.com/v1"


def test_notion_version_value():
    assert NOTION_VERSION == "2022-06-28"


# ---------------------------------------------------------------------------
# Regression: personal adapter must still import cleanly after refactor
# ---------------------------------------------------------------------------


def test_personal_notion_adapter_still_importable():
    from breadmind.personal.adapters.notion import NotionAdapter  # noqa: F401
    assert NotionAdapter is not None


def test_personal_notion_adapter_uses_common_constants():
    """After Task 1 refactor, personal adapter imports BASE_URL/NOTION_VERSION
    from notion_common. Verify the values are consistent."""
    import breadmind.personal.adapters.notion as _pa
    # The personal adapter exposes the constants either as its own names
    # or re-exports them from notion_common.
    assert _pa._BASE_URL == BASE_URL
    assert _pa._NOTION_VERSION == NOTION_VERSION
