"""Outbox -> Redis publish dispatcher.

Polls ``message_outbox`` rows, publishes a JSON envelope to
``channel:<channel_id>.events``, and deletes the published row. At-most-once
delivery — clients can recover missed events via the relay's BackfillSince
request (M2c). Closes M2a dep #8.

FU-1 (M2b) hardening:

* ``dispatch_one_batch`` uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so
  multiple concurrent dispatcher instances safely consume disjoint row
  sets. Locks release on transaction commit (after DELETE) or rollback
  (on connection error / cancel).
* ``OutboxDispatcher.run`` LISTENs on the ``outbox_new`` PostgreSQL
  channel (paired with the AFTER INSERT trigger from migration 021) so it
  wakes within milliseconds of an INSERT. A 5s safety polling tick
  guarantees forward progress even if a NOTIFY is missed (e.g., during
  the brief window before LISTEN registers, or across reconnects).
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Protocol

logger = logging.getLogger(__name__)


class _Publisher(Protocol):
    async def publish(self, channel: str, payload: str | bytes) -> int: ...


@asynccontextmanager
async def _acquire(db):
    """Yield a Connection regardless of whether ``db`` is a Pool/Database wrapper
    or an already-acquired ``asyncpg.Connection``.

    Detection: Pool/Database wrappers expose ``acquire()``; bare Connections
    do not.
    """
    if hasattr(db, "acquire"):
        async with db.acquire() as conn:
            yield conn
    else:
        # Already a Connection (or Connection-like); use as-is.
        yield db


async def dispatch_one_batch(db, redis: _Publisher, *, batch_size: int = 100) -> int:
    """Lock and publish up to ``batch_size`` outbox rows. Returns count published.

    Uses ``FOR UPDATE SKIP LOCKED`` so multiple concurrent dispatchers safely
    process disjoint row sets. The lock is released by transaction commit
    (after DELETE) or rollback (on connection error / cancel).

    Order: oldest rows first (FIFO via ``created_at ASC``). Failures on
    individual publishes are logged; their rows remain locked for the
    duration of the transaction and are NOT deleted, so they retry on the
    next batch (lock released on commit).

    Accepts either a Pool/Database wrapper (with ``acquire()``) or an
    already-acquired ``asyncpg.Connection``.
    """
    async with _acquire(db) as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                "SELECT id, channel_id, event_type, payload "
                "FROM message_outbox "
                "ORDER BY created_at ASC "
                "FOR UPDATE SKIP LOCKED "
                "LIMIT $1",
                batch_size,
            )
            if not rows:
                return 0

            published_ids = []
            for row in rows:
                raw_payload = row["payload"]
                envelope = {
                    "type": row["event_type"],
                    "payload": json.loads(raw_payload)
                    if isinstance(raw_payload, str)
                    else raw_payload,
                }
                channel = f"channel:{row['channel_id']}.events"
                try:
                    await redis.publish(channel, json.dumps(envelope))
                except Exception as e:  # noqa: BLE001
                    logger.warning("outbox publish failed id=%s: %s", row["id"], e)
                    continue
                published_ids.append(row["id"])

            if published_ids:
                await conn.execute(
                    "DELETE FROM message_outbox WHERE id = ANY($1::uuid[])",
                    published_ids,
                )
            return len(published_ids)


class OutboxDispatcher:
    """LISTEN/NOTIFY-aware long-running poll loop with safety polling fallback.

    Wakes within ms of an outbox INSERT (via ``LISTEN outbox_new``), and
    falls back to ``poll_interval`` polling to guarantee progress even if a
    NOTIFY is missed (e.g., LISTEN connection just established, dispatcher
    reconnected, or trigger somehow bypassed).

    Cancel the asyncio.Task to stop. Graceful shutdown: in-flight batch is
    allowed to complete (the SKIP LOCKED transaction commits or rolls back;
    cancel raises after the next await point).
    """

    def __init__(
        self,
        db,
        redis: _Publisher,
        *,
        poll_interval: float = 5.0,  # safety polling tick (FU-1 default = 5s)
        batch_size: int = 100,
    ):
        self._db = db
        self._redis = redis
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._wake = asyncio.Event()

    async def _listen_loop(self) -> None:
        """Open a dedicated connection and LISTEN for ``outbox_new`` notifies.

        The callback flips ``self._wake`` so ``run()`` can resume early. This
        coroutine spends its life parked on a long sleep so the connection
        stays open and asyncpg can deliver notifications. Cleanup removes
        the listener and releases the connection on cancel.
        """
        if hasattr(self._db, "acquire"):
            cm = self._db.acquire()
        else:
            cm = _passthrough(self._db)

        async with cm as conn:
            def _cb(*_args):  # asyncpg signature: (conn, pid, channel, payload)
                self._wake.set()

            await conn.add_listener("outbox_new", _cb)
            try:
                while True:
                    # Long park; cancellation is the normal exit path.
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "dispatcher listen connection lost; "
                    "falling back to safety polling"
                )
                raise
            finally:
                try:
                    await conn.remove_listener("outbox_new", _cb)
                except Exception:  # noqa: BLE001 - best-effort cleanup
                    logger.warning(
                        "listen unregister failed "
                        "(connection likely already closed)",
                        exc_info=True,
                    )

    async def run(self) -> None:
        listen_task = asyncio.create_task(self._listen_loop())
        try:
            while True:
                try:
                    n = await dispatch_one_batch(
                        self._db, self._redis, batch_size=self._batch_size
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    logger.exception("dispatcher batch failed: %s", e)
                    n = 0

                if n == 0:
                    # Idle: park on either NOTIFY wake or the safety polling tick.
                    try:
                        await asyncio.wait_for(
                            self._wake.wait(), timeout=self._poll_interval
                        )
                    except asyncio.TimeoutError:
                        pass  # safety polling fired
                    self._wake.clear()
                # Non-zero batch: immediately re-poll to drain under load.
        finally:
            listen_task.cancel()
            try:
                await listen_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("listen task crashed during shutdown")


@asynccontextmanager
async def _passthrough(conn):
    """Yield ``conn`` unchanged for already-acquired ``asyncpg.Connection`` callers."""
    yield conn
