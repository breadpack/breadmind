"""Common backfill pipeline contract.

Spec: docs/superpowers/specs/2026-04-26-backfill-pipeline-slack-design.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class BackfillItem:
    source_kind: str
    source_native_id: str
    source_uri: str
    source_created_at: datetime
    source_updated_at: datetime
    title: str
    body: str
    author: str | None
    parent_ref: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
