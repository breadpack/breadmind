"""Common backfill pipeline contract.

Spec: docs/superpowers/specs/2026-04-26-backfill-pipeline-slack-design.md
"""
from __future__ import annotations

import uuid
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


@dataclass
class JobProgress:
    discovered: int = 0
    filtered_out: int = 0
    redacted: int = 0
    embedded: int = 0
    stored: int = 0
    skipped_existing: int = 0
    errors: int = 0
    tokens_consumed: int = 0
    last_cursor: str | None = None


@dataclass(frozen=True)
class JobReport:
    job_id: uuid.UUID
    org_id: uuid.UUID
    source_kind: str
    dry_run: bool
    estimated_count: int
    estimated_tokens: int
    indexed_count: int
    skipped: dict[str, int] = field(default_factory=dict)
    errors: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: JobProgress = field(default_factory=JobProgress)
    sample_titles: list[str] = field(default_factory=list)
    budget_hit: bool = False
    cursor: str | None = None
