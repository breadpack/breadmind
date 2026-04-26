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
- :class:`~breadmind.kb.backfill.adapters.redmine.RedmineBackfillAdapter`
  — Redmine on-prem (issue + journal + wiki).
"""
from __future__ import annotations

from breadmind.kb.backfill.adapters.confluence import ConfluenceBackfillAdapter
from breadmind.kb.backfill.adapters.notion import NotionBackfillAdapter
from breadmind.kb.backfill.adapters.redmine import RedmineBackfillAdapter

__all__ = [
    "ConfluenceBackfillAdapter",
    "NotionBackfillAdapter",
    "RedmineBackfillAdapter",
]
