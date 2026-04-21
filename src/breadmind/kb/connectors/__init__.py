"""Connector framework for ingesting external sources into the KB pipeline."""
from __future__ import annotations

from breadmind.kb.connectors.base import BaseConnector, SyncResult

__all__ = ["BaseConnector", "SyncResult"]
