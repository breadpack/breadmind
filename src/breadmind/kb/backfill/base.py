"""Common backfill pipeline contract.

Spec: docs/superpowers/specs/2026-04-26-backfill-pipeline-slack-design.md
"""
from __future__ import annotations

import abc
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar


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


# WARNING: fields here are persisted to JSONB via dataclasses.asdict + json.dumps
# (see breadmind.kb.backfill.checkpoint.JobCheckpointer.checkpoint).
# Keep types JSON-serializable (no datetime/uuid). If you need a non-trivial
# type, add a custom serializer in checkpoint.py instead.
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
    aborted: bool = False
    error: str | None = None


class Skipped(Exception):
    """Raised inside discover() to signal a per-item skip with a reason key.

    The runner catches this, increments JobReport.skipped[reason] by 1,
    and continues. Adapters MAY use this instead of (or in addition to)
    filter() returning False with extra["_skip_reason"]."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class BackfillJob(abc.ABC):
    source_kind: ClassVar[str] = ""

    def __init__(
        self,
        *,
        org_id: uuid.UUID,
        source_filter: dict[str, Any],
        since: datetime,
        until: datetime,
        dry_run: bool,
        token_budget: int,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.org_id = org_id
        self.source_filter = source_filter
        self.since = since
        self.until = until
        self.dry_run = dry_run
        self.token_budget = token_budget
        self.config = config or {}

    @abc.abstractmethod
    async def prepare(self) -> None: ...

    @abc.abstractmethod
    def discover(self) -> AsyncIterator[BackfillItem]: ...

    @abc.abstractmethod
    def filter(self, item: BackfillItem) -> bool: ...

    @abc.abstractmethod
    def instance_id_of(self, source_filter: dict[str, Any]) -> str: ...

    async def teardown(self) -> None:
        return None

    def cursor_of(self, item: BackfillItem) -> str:
        return item.source_native_id
