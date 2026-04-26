"""Backfill pipeline orchestrator."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from breadmind.kb.backfill.base import (
    BackfillItem,
    BackfillJob,
    JobProgress,
    JobReport,
)
from breadmind.kb.backfill.budget import OrgMonthlyBudget
from breadmind.storage.database import Database

_SAMPLE_LIMIT = 10


@dataclass
class BackfillRunner:
    db: Database
    redactor: object | None
    embedder: object | None
    org_budget: OrgMonthlyBudget | None = None
    checkpoint_every_n: int = 50
    checkpoint_every_seconds: float = 30.0
    error_ratio_threshold: float = 0.10
    error_ratio_min_items: int = 200

    async def run(self, job: BackfillJob) -> JobReport:
        await job.prepare()
        progress = JobProgress()
        skipped: dict[str, int] = {}
        sample_titles: list[str] = []
        started_at = datetime.now(timezone.utc)

        last_item: BackfillItem | None = None
        async for item in job.discover():
            progress.discovered += 1
            if not job.filter(item):
                reason = item.extra.get("_skip_reason", "filtered")
                skipped[reason] = skipped.get(reason, 0) + 1
                progress.filtered_out += 1
                continue
            # Token estimate (cheap len/4 heuristic per spec §4).
            progress.tokens_consumed += len(item.body) // 4
            if len(sample_titles) < _SAMPLE_LIMIT:
                sample_titles.append(item.title)
            if job.dry_run:
                last_item = item
                continue
            # Real-run pipeline lands in Task 8/9.
            raise NotImplementedError("real-run pipeline lands in Task 8/9")

        await job.teardown()
        finished_at = datetime.now(timezone.utc)
        return JobReport(
            job_id=uuid.uuid4(),
            org_id=job.org_id,
            source_kind=job.source_kind,
            dry_run=job.dry_run,
            estimated_count=progress.discovered - progress.filtered_out,
            estimated_tokens=progress.tokens_consumed,
            indexed_count=0,
            skipped=skipped,
            errors=progress.errors,
            started_at=started_at,
            finished_at=finished_at,
            progress=progress,
            sample_titles=sample_titles,
            budget_hit=False,
            cursor=job.cursor_of(last_item) if last_item else None,
        )
