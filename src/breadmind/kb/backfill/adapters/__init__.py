"""Backfill adapters package.

Each adapter implements :class:`breadmind.kb.backfill.base.BackfillJob`
for a specific source system.

Available adapters
------------------
- :class:`~breadmind.kb.backfill.adapters.notion.NotionBackfillAdapter`
  — Notion (backfill only).
- :class:`~breadmind.kb.backfill.adapters.confluence.ConfluenceBackfillAdapter`
  — Confluence Cloud / Server (backfill only; incremental is
  :class:`breadmind.kb.connectors.confluence.ConfluenceConnector`).
"""
from __future__ import annotations

from breadmind.kb.backfill.adapters.confluence import ConfluenceBackfillAdapter
from breadmind.kb.backfill.adapters.notion import NotionBackfillAdapter

__all__ = ["ConfluenceBackfillAdapter", "NotionBackfillAdapter"]
