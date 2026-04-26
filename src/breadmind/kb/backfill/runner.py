"""Backfill pipeline orchestrator."""
from __future__ import annotations

import dataclasses
import time
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
from breadmind.kb.backfill.checkpoint import JobCheckpointer
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
    checkpointer: JobCheckpointer | None = None
    created_by: str = "system"
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

        # T9: insert kb_backfill_jobs row (status='running') so the row exists
        # before we touch any items. Stays None when no checkpointer was wired
        # (existing T7/T8 dry-run/unit tests still work without DB writes).
        job_id: uuid.UUID | None = None
        if self.checkpointer is not None:
            job_id = await self.checkpointer.start(
                org_id=job.org_id,
                source_kind=job.source_kind,
                source_filter=job.source_filter,
                instance_id=job.instance_id_of(job.source_filter),
                since=job.since,
                until=job.until,
                dry_run=job.dry_run,
                token_budget=job.token_budget,
                created_by=self.created_by,
            )

        # T9: cadence locals — checkpoint every N discovered items OR every
        # checkpoint_every_seconds (whichever fires first). monotonic time
        # so we are immune to wall-clock jumps.
        last_cp_count = 0
        last_cp_time = time.monotonic()

        # M3: wrap the discover loop in try/finally so teardown always runs,
        # even if discover() raises. _maybe_abort no longer raises; on error-
        # rate breach we set ``aborted`` and break, so the partial JobReport
        # still flows out (T9 needs counts + last cursor for resume).
        #
        # T17 (review fix): per-channel fail-closed on archive lives INSIDE
        # the adapter (spec §11 P4). The adapter records archived channel ids
        # in ``job._archived_channels`` and continues with siblings. The
        # runner just reads that set after discover finishes — no slack-
        # specific exception needs to cross the runner boundary.
        try:
            # M4: ``Skipped`` raised mid-yield from discover() will bubble
            # out of the ``async for`` here; per-item ``Skipped`` (raised
            # inside the loop body) is caught explicitly below.
            async for item in job.discover():
                progress.discovered += 1
                try:
                    if not job.filter(item):
                        reason = item.extra.get("_skip_reason", "filtered")
                        skipped[reason] = skipped.get(reason, 0) + 1
                        progress.filtered_out += 1
                        last_cp_count, last_cp_time = await self._maybe_checkpoint(
                            job_id, progress, skipped,
                            job.cursor_of(last_item) if last_item else None,
                            last_cp_count, last_cp_time,
                        )
                        continue

                    if len(sample_titles) < _SAMPLE_LIMIT:
                        sample_titles.append(item.title)

                    if job.dry_run:
                        # Token estimate (cheap len/4 heuristic per spec §4).
                        # In dry-run we charge here because no later pipeline
                        # step exists. Real-run charges post-redact (I2).
                        progress.tokens_consumed += len(item.body) // 4
                        last_item = item
                        last_cp_count, last_cp_time = await self._maybe_checkpoint(
                            job_id, progress, skipped,
                            job.cursor_of(last_item),
                            last_cp_count, last_cp_time,
                        )
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
                        # T9: still checkpoint by discovered-count even on
                        # individual item failures so resume cursor advances
                        # past the failed run if abort threshold is not yet
                        # breached.
                        last_cp_count, last_cp_time = await self._maybe_checkpoint(
                            job_id, progress, skipped,
                            job.cursor_of(last_item) if last_item else None,
                            last_cp_count, last_cp_time,
                        )
                        continue
                    if outcome is _Outcome.STORED:
                        last_item = item
                    # T9: checkpoint after every item (STORED or DROPPED) by
                    # discovered count; cadence gating lives in the helper.
                    last_cp_count, last_cp_time = await self._maybe_checkpoint(
                        job_id, progress, skipped,
                        job.cursor_of(last_item) if last_item else None,
                        last_cp_count, last_cp_time,
                    )
                except Skipped as e:
                    # M4: per-item Skipped (raised by filter/transform inside
                    # the loop body) becomes a counted skip and we continue.
                    skipped[e.reason] = skipped.get(e.reason, 0) + 1
                    progress.filtered_out += 1
                    last_cp_count, last_cp_time = await self._maybe_checkpoint(
                        job_id, progress, skipped,
                        job.cursor_of(last_item) if last_item else None,
                        last_cp_count, last_cp_time,
                    )
                    continue
        finally:
            # T17 (review fix): the adapter records mid-run archived channel
            # ids in ``_archived_channels`` and keeps producing items from
            # siblings. Fold the count into ``skipped['archived']`` here so
            # the report (and persisted checkpoint below) reflect spec §11 P4
            # semantics. Use ``max`` to merge with any prior value the adapter
            # or earlier code path may have set.
            archived_ids = getattr(job, "_archived_channels", set()) or set()
            if archived_ids:
                skipped["archived"] = max(
                    skipped.get("archived", 0), len(archived_ids))
            # T9-review I1: capture but do NOT propagate teardown errors until
            # AFTER the kb_backfill_jobs row converges to a terminal status.
            # Otherwise a connector cleanup blip would leave the row stuck at
            # status='running' forever — hostile to ops alerting.
            teardown_err: BaseException | None = None
            try:
                await job.teardown()
            except Exception as exc:
                teardown_err = exc
                # Don't shadow a primary error_message captured by abort logic.
                if error_message is None:
                    error_message = f"teardown failed: {exc}"
                    aborted = True
            # T9: finalize the kb_backfill_jobs row even on abort/exception.
            # Final checkpoint write captures the latest cursor + counts so
            # a resumer reads the truth, then finish() stamps terminal state.
            if self.checkpointer is not None and job_id is not None:
                await self.checkpointer.checkpoint(
                    job_id=job_id,
                    cursor=job.cursor_of(last_item) if last_item else None,
                    progress=dataclasses.asdict(progress),
                    skipped=skipped,
                )
                if aborted:
                    await self.checkpointer.finish(
                        job_id=job_id,
                        status="failed",
                        error=error_message,
                    )
                elif budget_hit:
                    await self.checkpointer.finish(
                        job_id=job_id,
                        status="paused",
                        error=None,
                    )
                else:
                    await self.checkpointer.finish(
                        job_id=job_id,
                        status="completed",
                        error=None,
                    )
            # Re-raise the original teardown error after row convergence so
            # the caller still observes the underlying failure.
            if teardown_err is not None:
                raise teardown_err

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
            # If aborted/budget-hit before any STORED item, cursor=None signals
            # the resumer to restart from since_ts (no prior progress to advance
            # past).
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
        # Postgres' partial-unique-index ``ON CONFLICT`` only fires for
        # rows that satisfy the index predicate; on conflict ``DO NOTHING``
        # returns no row (nothing was inserted), so we need a separate
        # lookup before writing the kb_sources citation.
        try:
            row = await self.db.fetchrow(
                """
                INSERT INTO org_knowledge
                    (project_id, title, body, category, embedding, author,
                     source_kind, source_native_id,
                     source_created_at, source_updated_at,
                     parent_ref)
                VALUES ($1, $2, $3, $4, $5::vector, $6,
                        $7, $8, $9, $10, $11)
                ON CONFLICT (project_id, source_kind,
                             source_native_id)
                    WHERE source_native_id IS NOT NULL
                          AND superseded_by IS NULL
                    DO NOTHING
                RETURNING id
                """,
                job.org_id,
                item.title,
                redacted_body,
                item.source_kind,  # use source_kind as category for now
                _vec_literal(vec),
                item.author,
                item.source_kind,
                item.source_native_id,
                item.source_created_at,
                item.source_updated_at,
                item.parent_ref,
            )
            if row is not None:
                await self.db.execute(
                    """
                    INSERT INTO kb_sources
                        (knowledge_id, source_type, source_uri, source_ref)
                    VALUES ($1, $2, $3, $4)
                    """,
                    row["id"],
                    item.source_kind,
                    item.source_uri,
                    item.source_native_id,
                )
                progress.stored += 1
            else:
                # Conflict-skipped: row already existed for this
                # (project_id, source_kind, source_native_id). Treat as a
                # successful idempotent re-run, not an error.
                skipped["skipped_existing"] = (
                    skipped.get("skipped_existing", 0) + 1
                )
                progress.skipped_existing += 1
        except Exception:
            progress.errors += 1
            return _Outcome.ERRORED

        return _Outcome.STORED

    async def _maybe_checkpoint(
        self,
        job_id: uuid.UUID | None,
        progress: JobProgress,
        skipped: dict[str, int],
        cursor: str | None,
        last_cp_count: int,
        last_cp_time: float,
    ) -> tuple[int, float]:
        """Write a checkpoint row if the N-item or T-second cadence fired.

        Returns updated ``(last_cp_count, last_cp_time)`` so the caller can
        rebind its cadence locals. No-op (returns inputs) when the
        checkpointer is unwired or the cadence thresholds have not been
        crossed since the previous write.
        """
        if self.checkpointer is None or job_id is None:
            return last_cp_count, last_cp_time
        now = time.monotonic()
        delta_n = progress.discovered - last_cp_count
        delta_t = now - last_cp_time
        if (
            delta_n < self.checkpoint_every_n
            and delta_t < self.checkpoint_every_seconds
        ):
            return last_cp_count, last_cp_time
        await self.checkpointer.checkpoint(
            job_id=job_id,
            cursor=cursor,
            progress=dataclasses.asdict(progress),
            skipped=skipped,
        )
        return progress.discovered, now

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
