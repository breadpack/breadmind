"""Log streaming for JobTracker (extracted from job_tracker.py).

Owns log listeners + per-phase line counters + LogBuffer binding.
JobTracker delegates `add_log_listener`, `append_log`, etc. to an
instance of this class.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from breadmind.metrics import coding_phase_log_lines_total

logger = logging.getLogger(__name__)


class JobLogStream:
    def __init__(self, db_writer: Any | None = None) -> None:
        self._db_writer = db_writer
        self._buffer: Any | None = None  # LogBuffer
        self._listeners: list[Callable] = []
        self._line_counters: dict[tuple[str, int], int] = {}

    # ── Wiring ──────────────────────────────────────────────────────────

    def bind_buffer(self, buffer: Any) -> None:
        self._buffer = buffer

    def add_listener(self, cb: Callable) -> None:
        self._listeners.append(cb)

    def remove_listener(self, cb: Callable) -> None:
        self._listeners = [c for c in self._listeners if c is not cb]

    # ── Counters ────────────────────────────────────────────────────────

    def reset_phase_counter(self, job_id: str, step: int) -> None:
        self._line_counters[(job_id, step)] = 0

    def evict_job_counters(self, job_id: str) -> None:
        for key in [k for k in self._line_counters if k[0] == job_id]:
            self._line_counters.pop(key, None)

    # ── Append ──────────────────────────────────────────────────────────

    async def append(self, job_id: str, step: int, text: str) -> None:
        key = (job_id, step)
        self._line_counters[key] = self._line_counters.get(key, 0) + 1
        line_no = self._line_counters[key]
        ts = datetime.now(timezone.utc)
        coding_phase_log_lines_total.inc()
        for cb in list(self._listeners):
            try:
                asyncio.ensure_future(cb(job_id, step, line_no, ts, text))
            except RuntimeError:
                pass
        if self._buffer is not None:
            if self._db_writer is not None:
                await self._db_writer.join()
            await self._buffer.append(job_id, step, line_no, text)

    # ── Force flush (called from JobTracker.complete_phase) ─────────────

    def force_flush_phase(self, job_id: str, step: int) -> None:
        """Best-effort signal to flush a phase's pending batch.

        None-check + buffer delegation encapsulated here. Caller (JobTracker)
        is in a sync context so this fires-and-forgets via ensure_future.
        """
        if self._buffer is None:
            return
        try:
            asyncio.ensure_future(self._buffer.force_flush(job_id, step))
        except RuntimeError:
            pass  # no running loop

    # ── Default flush_fn factory (moved from JobTracker) ────────────────

    @staticmethod
    def make_default_flush(store: Any) -> Callable:
        async def flush(
            batch: list[tuple[str, int, int, datetime, str]],
        ) -> None:
            by_job: dict[str, list[tuple[int, int, datetime, str]]] = {}
            for job_id, step, line_no, ts, text in batch:
                by_job.setdefault(job_id, []).append((step, line_no, ts, text))
            for job_id, items in by_job.items():
                await store.insert_log_batch(job_id, items)

        return flush
