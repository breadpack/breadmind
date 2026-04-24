"""Batch log buffer for streaming phase logs to DB.

Aggregates append_log calls per (job_id, step), flushes at size threshold
or after idle time_threshold_s. Enforces per-phase ring cap to bound memory.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable

from breadmind.metrics import coding_log_drops_total, tracer

logger = logging.getLogger(__name__)

FlushFn = Callable[[list[tuple[str, int, int, datetime, str]]], Awaitable[None]]
# batch item tuple: (job_id, step, line_no, ts, text) — matches JobStore.insert_log_batch
# (with adapter stripping job_id and passing tuples of (step, line_no, ts, text)).


class LogBuffer:
    def __init__(
        self,
        *,
        flush_fn: FlushFn,
        size_threshold: int = 50,
        time_threshold_s: float = 1.0,
        per_phase_cap: int = 5000,
        on_drop: Callable[[int], None] | None = None,
    ) -> None:
        self._flush_fn = flush_fn
        self._size_threshold = size_threshold
        self._time_threshold_s = time_threshold_s
        self._per_phase_cap = per_phase_cap
        self._on_drop = on_drop
        # key: (job_id, step); value: list of (line_no, ts, text)
        self._buffers: dict[tuple[str, int], list[tuple[int, datetime, str]]] = {}
        self._last_flush_ts: dict[tuple[str, int], float] = {}
        self._lock = asyncio.Lock()
        # Worker lifecycle (Task 9): start()/stop() manage a background drain
        # loop. _wake signals immediate drain (size-triggered or force_flush);
        # _stop signals graceful shutdown. _force_keys accumulates keys that
        # must be flushed on the next drain regardless of age/size.
        self._wake = asyncio.Event()
        self._stop = asyncio.Event()
        self._worker: asyncio.Task | None = None
        self._force_keys: set[tuple[str, int]] = set()

    async def start(self) -> None:
        """Start the background drain worker. Idempotent."""
        if self._worker is None or self._worker.done():
            self._stop.clear()
            self._worker = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        """Signal the worker to stop and await its final drain."""
        self._stop.set()
        self._wake.set()
        if self._worker is not None:
            try:
                await self._worker
            except Exception:
                # Worker errors must not prevent clean shutdown.
                pass
            self._worker = None

    async def _worker_loop(self) -> None:
        """Wake on _wake event or every time_threshold_s; drain; repeat."""
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(
                    self._wake.wait(), timeout=self._time_threshold_s,
                )
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            await self._drain_once()
        # Final drain on stop so in-flight batches aren't lost.
        await self._drain_once()

    async def _drain_once(self) -> None:
        """Snapshot eligible buffers under lock, flush outside lock."""
        async with self._lock:
            now = time.monotonic()
            keys_to_flush: list[tuple[str, int]] = []
            for k, buf in self._buffers.items():
                if not buf:
                    continue
                aged = now - self._last_flush_ts.get(k, 0.0) >= self._time_threshold_s
                sized = len(buf) >= self._size_threshold
                forced = k in self._force_keys
                if aged or sized or forced:
                    keys_to_flush.append(k)
            payloads: list[
                tuple[tuple[str, int], list[tuple[str, int, int, datetime, str]]]
            ] = []
            for k in keys_to_flush:
                buf = self._buffers[k]
                payload = [(k[0], k[1], n, ts, text) for (n, ts, text) in buf]
                self._buffers[k] = []
                self._last_flush_ts[k] = now
                payloads.append((k, payload))
            self._force_keys.difference_update(keys_to_flush)
        # Flush outside lock — concurrent gather, exceptions absorbed so a
        # single key's DB failure doesn't block siblings.
        if payloads:
            await asyncio.gather(
                *[self._flush_payload(k, p) for k, p in payloads],
                return_exceptions=True,
            )

    async def _flush_payload(
        self,
        key: tuple[str, int],
        payload: list[tuple[str, int, int, datetime, str]],
    ) -> None:
        with tracer.start_as_current_span("coding.log.flush") as span:
            try:
                span.set_attribute("coding.job_id", key[0])
                span.set_attribute("coding.step", key[1])
                span.set_attribute("coding.batch_size", len(payload))
            except Exception:
                pass
            try:
                await self._flush_fn(payload)
            except Exception as exc:
                coding_log_drops_total.labels(reason="db_flush_fail").inc(len(payload))
                try:
                    span.record_exception(exc)
                except Exception:
                    pass
                logger.warning("LogBuffer flush failed for %s: %s", key, exc)
                # Do NOT re-raise — gather() must still succeed for sibling keys.

    async def append(self, job_id: str, step: int, line_no: int, text: str) -> None:
        key = (job_id, step)
        now = datetime.now(timezone.utc)
        async with self._lock:
            buf = self._buffers.setdefault(key, [])
            buf.append((line_no, now, text))
            self._last_flush_ts.setdefault(key, time.monotonic())
            # Enforce cap
            if len(buf) > self._per_phase_cap:
                dropped = len(buf) - self._per_phase_cap
                del buf[:dropped]
                coding_log_drops_total.labels(reason="buffer_full").inc(dropped)
                if self._on_drop:
                    self._on_drop(dropped)
            # Size-triggered flush
            if len(buf) >= self._size_threshold:
                await self._flush_key_locked(key)

    async def tick(self) -> None:
        """Check all buffers; flush those that have aged past time_threshold_s."""
        now = time.monotonic()
        async with self._lock:
            keys = [
                k
                for k in self._buffers
                if self._buffers[k]
                and now - self._last_flush_ts.get(k, 0.0) >= self._time_threshold_s
            ]
            for k in keys:
                await self._flush_key_locked(k)

    async def force_flush(self, job_id: str, step: int) -> None:
        key = (job_id, step)
        async with self._lock:
            if self._buffers.get(key):
                await self._flush_key_locked(key)

    async def _flush_key_locked(self, key: tuple[str, int]) -> None:
        job_id, step = key
        buf = self._buffers.get(key) or []
        if not buf:
            return
        self._buffers[key] = []
        self._last_flush_ts[key] = time.monotonic()
        payload = [(job_id, step, line_no, ts, text) for (line_no, ts, text) in buf]
        with tracer.start_as_current_span("coding.log.flush") as span:
            try:
                span.set_attribute("coding.job_id", job_id)
                span.set_attribute("coding.step", step)
                span.set_attribute("coding.batch_size", len(payload))
            except Exception:
                # OTel is best-effort; attribute-set failures must not
                # break a flush.
                pass
            try:
                await self._flush_fn(payload)
            except Exception as exc:
                # DB flush failure: lines are already pulled out of the
                # buffer, so they're effectively dropped. Record the drop
                # size and re-raise so the caller (tick/force_flush/append)
                # stays in charge of retry policy.
                coding_log_drops_total.labels(reason="db_flush_fail").inc(len(payload))
                try:
                    span.record_exception(exc)
                except Exception:
                    pass
                raise
