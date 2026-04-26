"""Backfill pipeline orchestrator."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, auto

from breadmind.kb.backfill.base import (
    BackfillItem,
    BackfillJob,
    JobProgress,
    JobReport,
    Skipped,
)
from breadmind.kb.backfill.budget import OrgMonthlyBudget
from breadmind.kb.redactor import SecretDetected
from breadmind.storage.database import Database

_SAMPLE_LIMIT = 10


def _vec_literal(vec: list[float]) -> str:
    """Render a Python list as the pgvector text-input literal.

    Mirrors :func:`breadmind.kb.review_queue._vec` — pgvector accepts
    ``'[f1,f2,...]'`` with 6-decimal precision when cast via ``$N::vector``.
    """
    return "[" + ",".join(f"{float(v):.6f}" for v in vec) + "]"


class _Outcome(Enum):
    """Result of a single per-item pipeline pass.

    The outer loop in :meth:`BackfillRunner.run` uses this to decide
    whether to break (budget) or to consult :meth:`_maybe_abort` (errors).
    Keeping the side-effects (break / abort capture) in the outer loop
    leaves :meth:`_process_item` pure-ish — only ``progress`` /
    ``skipped`` / ``sample_titles`` mutation, no control flow.
    """

    STORED = auto()        # full pipeline succeeded; advance last_item
    DROPPED = auto()       # filter / Skipped / SecretDetected / dry-run
    ERRORED = auto()       # redact/embed/store raised — caller checks abort
    BUDGET_HALT = auto()   # token budget gate fired — caller breaks loop


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
        budget_hit = False
        aborted = False
        error_message: str | None = None
        last_item: BackfillItem | None = None

        # M3: wrap the discover loop in try/finally so teardown always runs,
        # even if discover() raises. _maybe_abort no longer raises; on error-
        # rate breach we set ``aborted`` and break, so the partial JobReport
        # still flows out (T9 needs counts + last cursor for resume).
        try:
            # M4: ``Skipped`` raised mid-yield from discover() will bubble
            # out of the ``async for`` here; per-item ``Skipped`` (raised
            # inside the loop body) is caught explicitly below. T9 may
            # need the verbose iter-level form for resume.
            async for item in job.discover():
                progress.discovered += 1
                try:
                    if not job.filter(item):
                        reason = item.extra.get("_skip_reason", "filtered")
                        skipped[reason] = skipped.get(reason, 0) + 1
                        progress.filtered_out += 1
                        continue

                    if len(sample_titles) < _SAMPLE_LIMIT:
                        sample_titles.append(item.title)

                    if job.dry_run:
                        # Token estimate (cheap len/4 heuristic per spec §4).
                        # In dry-run we charge here because no later pipeline
                        # step exists. Real-run charges post-redact (I2).
                        progress.tokens_consumed += len(item.body) // 4
                        last_item = item
                        continue

                    outcome = await self._process_item(
                        item, job, progress, skipped
                    )
                    if outcome is _Outcome.BUDGET_HALT:
                        budget_hit = True
                        break
                    if outcome is _Outcome.ERRORED:
                        should_abort, msg = self._maybe_abort(progress)
                        if should_abort:
                            aborted = True
                            error_message = msg
                            break
                        continue
                    if outcome is _Outcome.STORED:
                        last_item = item
                except Skipped as e:
                    # M4: per-item Skipped (raised by filter/transform inside
                    # the loop body) becomes a counted skip and we continue.
                    skipped[e.reason] = skipped.get(e.reason, 0) + 1
                    progress.filtered_out += 1
                    continue
        finally:
            await job.teardown()

        finished_at = datetime.now(timezone.utc)

        # M2: estimated_count formula differs between dry-run and real-run.
        if job.dry_run:
            estimated_count = progress.discovered - progress.filtered_out
            indexed_count = 0
        else:
            estimated_count = (
                progress.discovered
                - progress.filtered_out
                - progress.errors
                - skipped.get("redact_dropped", 0)
                - skipped.get("budget_halted", 0)
            )
            indexed_count = progress.stored

        return JobReport(
            job_id=uuid.uuid4(),
            org_id=job.org_id,
            source_kind=job.source_kind,
            dry_run=job.dry_run,
            estimated_count=estimated_count,
            estimated_tokens=progress.tokens_consumed,
            indexed_count=indexed_count,
            skipped=skipped,
            errors=progress.errors,
            started_at=started_at,
            finished_at=finished_at,
            progress=progress,
            sample_titles=sample_titles,
            budget_hit=budget_hit,
            cursor=job.cursor_of(last_item) if last_item else None,
            aborted=aborted,
            error=error_message,
        )

    async def _process_item(
        self,
        item: BackfillItem,
        job: BackfillJob,
        progress: JobProgress,
        skipped: dict[str, int],
    ) -> _Outcome:
        """Run the per-item real-run pipeline (gate → redact → embed → store).

        Returns an :class:`_Outcome` indicating what the outer loop should
        do next. Mutates ``progress`` and ``skipped`` in place but does not
        break / raise on its own — the outer loop owns the abort decision.
        """
        # I2: charge token budget *projected* (peek without committing) so a
        # redact_dropped item doesn't consume budget retroactively. The
        # actual increment lands post-redact below.
        projected = len(item.body) // 4
        if progress.tokens_consumed + projected >= job.token_budget:
            skipped["budget_halted"] = skipped.get("budget_halted", 0) + 1
            return _Outcome.BUDGET_HALT

        # Redact (abort_if_secrets first, then mask).
        try:
            await self.redactor.abort_if_secrets(item.body)
            redacted_body, _map_id = await self.redactor.redact(
                item.body, session_id=str(job.org_id)
            )
            progress.redacted += 1
        except SecretDetected:
            skipped["redact_dropped"] = skipped.get("redact_dropped", 0) + 1
            return _Outcome.DROPPED
        except Exception:
            progress.errors += 1
            return _Outcome.ERRORED

        # I2: charge token budget post-redact, before embed (spec §4 wording
        # "before calling embed"). Items that filtered in but redact-dropped
        # do not pollute the per-org reconciliation in T9.
        progress.tokens_consumed += projected

        # Embed.
        try:
            vec = await self.embedder.encode(redacted_body)
            progress.embedded += 1
        except Exception:
            progress.errors += 1
            return _Outcome.ERRORED

        # Store.
        try:
            await self.db.execute(
                """
                INSERT INTO org_knowledge
                    (project_id, title, body, category, embedding,
                     source_kind, source_native_id,
                     source_created_at, source_updated_at,
                     parent_ref)
                VALUES ($1, $2, $3, $4, $5::vector,
                        $6, $7, $8, $9, $10)
                ON CONFLICT (project_id, source_kind,
                             source_native_id)
                    WHERE source_native_id IS NOT NULL
                          AND superseded_by IS NULL
                    DO NOTHING
                """,
                job.org_id,
                item.title,
                redacted_body,
                item.source_kind,  # use source_kind as category for now
                _vec_literal(vec),
                item.source_kind,
                item.source_native_id,
                item.source_created_at,
                item.source_updated_at,
                item.parent_ref,
            )
            progress.stored += 1
        except Exception:
            progress.errors += 1
            return _Outcome.ERRORED

        return _Outcome.STORED

    def _maybe_abort(
        self, progress: JobProgress
    ) -> tuple[bool, str | None]:
        """Decide whether the cumulative error rate breaches the threshold.

        Returns ``(should_abort, message)``. Does NOT raise — the caller
        captures the message into the partial :class:`JobReport` so T9 can
        resume from the last cursor instead of losing all state to a
        propagating exception (I1).
        """
        if progress.discovered < self.error_ratio_min_items:
            return False, None
        if progress.errors > self.error_ratio_threshold * progress.discovered:
            msg = (
                f"error rate {progress.errors}/{progress.discovered} "
                f"exceeds {self.error_ratio_threshold:.0%} threshold"
            )
            return True, msg
        return False, None
