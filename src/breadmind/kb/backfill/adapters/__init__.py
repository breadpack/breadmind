"""Backfill adapters package.

Each adapter implements :class:`breadmind.kb.backfill.base.BackfillJob`
for a specific source system.

Available adapters
------------------
- :class:`~breadmind.kb.backfill.adapters.confluence.ConfluenceBackfillAdapter`
  — Confluence Cloud / Server (backfill only; incremental is
  :class:`breadmind.kb.connectors.confluence.ConfluenceConnector`).
"""
from breadmind.kb.backfill.adapters.confluence import ConfluenceBackfillAdapter

__all__ = ["ConfluenceBackfillAdapter"]
