"""FastAPI lifespan helpers for migrations and background tasks.

This module is the single source of truth for the FastAPI ``lifespan``
context manager wired into ``WebApp`` (see ``breadmind.web.app``).

It runs alembic auto-migrate on startup (gated by
``BREADMIND_AUTO_MIGRATE``, default ``true``) and starts/stops the
:class:`~breadmind.messenger.dispatcher.OutboxDispatcher` background
task that drains ``message_outbox`` rows to Redis pub/sub.

The dispatcher start is deliberately tolerant of no-DB / no-Redis
environments (e.g., unit tests using ``TestClient`` without a real
Postgres or Redis). It is also gated by
``BREADMIND_OUTBOX_DISPATCHER_ENABLED`` (default ``true``) so deploys
that run a separate dispatcher process can opt out.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Final

from breadmind.messenger.dispatcher import OutboxDispatcher
from breadmind.storage.migrate_runner import DatabaseUrlNotSet, run_upgrade

if TYPE_CHECKING:
    from asyncpg import Pool

logger = logging.getLogger(__name__)


# Truthy strings for env-driven boolean flags. Matches typical conventions
# (compatible with the env-flag parsing used elsewhere in BreadMind).
_TRUTHY: Final[set[str]] = {"true", "1", "yes", "on"}

# Maximum time we wait for the dispatcher task to acknowledge cancellation
# during shutdown. The dispatcher's ``run()`` loop has frequent await
# points so 5s is comfortably above the worst-case batch latency.
_SHUTDOWN_TIMEOUT_SEC: Final[float] = 5.0


def auto_migrate_enabled() -> bool:
    """Return ``True`` when startup auto-migration should run.

    Reads ``BREADMIND_AUTO_MIGRATE`` (default: ``true``). Operators can
    set it to ``false``/``0``/``no``/``off`` to disable the auto-migrate
    on startup (e.g., when running migrations manually via ``breadmind
    migrate up`` in a deploy pipeline).
    """
    return os.environ.get("BREADMIND_AUTO_MIGRATE", "true").strip().lower() in _TRUTHY


def outbox_dispatcher_enabled() -> bool:
    """Return ``True`` when the in-process OutboxDispatcher should start.

    Reads ``BREADMIND_OUTBOX_DISPATCHER_ENABLED`` (default: ``true``).
    Set to ``false``/``0``/``no``/``off`` when running a dedicated
    out-of-process dispatcher worker, or in test environments that
    don't want the lifespan to spawn a background task.
    """
    return (
        os.environ.get("BREADMIND_OUTBOX_DISPATCHER_ENABLED", "true")
        .strip()
        .lower()
        in _TRUTHY
    )


async def maybe_run_migration() -> None:
    """Apply migrations if ``BREADMIND_AUTO_MIGRATE`` is enabled (default true).

    The PG advisory lock inside ``run_upgrade`` makes concurrent invocations
    safe; only one worker actually performs the upgrade; others wait for
    the lock and then no-op (alembic detects already-at-head).

    No-DB environments (most unit tests using ``TestClient``) are tolerated
    by catching ``DatabaseUrlNotSet`` (the typed sentinel raised by
    ``migrate_runner._db_url`` when neither ``BREADMIND_DB_URL`` nor
    ``DATABASE_URL`` is set) and logging+skipping. Other migration failures
    still propagate so a misconfigured deploy doesn't silently start with
    a stale schema.
    """
    if not auto_migrate_enabled():
        logger.info("BREADMIND_AUTO_MIGRATE disabled; skipping startup migration")
        return
    logger.info("running startup alembic upgrade head")
    try:
        rev = await asyncio.to_thread(run_upgrade, "head")
    except DatabaseUrlNotSet as e:
        logger.info(
            "BREADMIND_DB_URL/DATABASE_URL not set; skipping startup migration: %s", e
        )
        return
    logger.info("alembic upgrade complete: rev=%s", rev)


async def acquire_pg_pool() -> Pool:
    """Return an asyncpg pool for the messenger dispatcher.

    Constructs a fresh pool from ``BREADMIND_DB_URL`` / ``DATABASE_URL``
    so the dispatcher has its own pool independent of the main
    ``Database`` wrapper (the dispatcher's LISTEN connection holds an
    open connection long-term, and we don't want it to starve handler
    queries).

    Raises :class:`DatabaseUrlNotSet` when neither env var is set so the
    caller can degrade gracefully (no-DB unit tests). Other failures
    (DNS, auth, connection refused, missing optional dep) propagate so a
    misconfigured production deploy fails loudly on startup rather than
    silently running without a dispatcher.
    """
    import asyncpg  # local import — keep cold-start light

    url = os.environ.get("BREADMIND_DB_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise DatabaseUrlNotSet(
            "BREADMIND_DB_URL/DATABASE_URL not set; cannot create asyncpg pool"
        )
    return await asyncpg.create_pool(url, min_size=2, max_size=10)


async def _maybe_start_dispatcher(
    app,
) -> tuple[Pool | None, asyncio.Task | None]:
    """Start :class:`OutboxDispatcher` if all prerequisites are satisfied.

    Returns ``(pool, task)`` on success, or ``(None, None)`` when any
    skip-gate fires. Each skip path logs at INFO so operators can see
    which gate triggered.

    Skip gates (in order):
      1. ``BREADMIND_OUTBOX_DISPATCHER_ENABLED`` is falsy.
      2. ``app.state.redis`` is unset/None.
      3. ``BREADMIND_DB_URL`` / ``DATABASE_URL`` is unset
         (:class:`DatabaseUrlNotSet`).

    Other ``acquire_pg_pool`` failures (connection refused, auth, DNS,
    ImportError) propagate so a misconfigured deploy fails loudly.
    """
    if not outbox_dispatcher_enabled():
        logger.info(
            "BREADMIND_OUTBOX_DISPATCHER_ENABLED disabled; skipping dispatcher start"
        )
        return None, None
    redis = getattr(app.state, "redis", None)
    if redis is None:
        logger.info(
            "app.state.redis not configured; skipping OutboxDispatcher start"
        )
        return None, None
    try:
        pool = await acquire_pg_pool()
    except DatabaseUrlNotSet as e:
        logger.info(
            "BREADMIND_DB_URL/DATABASE_URL not set; skipping dispatcher start: %s",
            e,
        )
        return None, None
    dispatcher = OutboxDispatcher(pool, redis)
    task = asyncio.create_task(dispatcher.run(), name="messenger-outbox-dispatcher")
    app.state.outbox_dispatcher_task = task
    logger.info("OutboxDispatcher started")
    return pool, task


async def _stop_dispatcher(
    app,
    pool: Pool | None,
    task: asyncio.Task | None,
) -> None:
    """Cancel the dispatcher task and close the PG pool, best-effort.

    Clears ``app.state.outbox_dispatcher_task`` so a subsequent lifespan
    cycle (or other inspectors) doesn't see a stale, completed task
    reference.
    """
    if task is None:
        return
    logger.info("cancelling OutboxDispatcher")
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=_SHUTDOWN_TIMEOUT_SEC)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    except Exception:  # noqa: BLE001 - best-effort shutdown
        logger.exception("OutboxDispatcher raised during shutdown")
    if pool is not None:
        try:
            await pool.close()
        except Exception:  # noqa: BLE001
            logger.warning("pg pool close failed", exc_info=True)
    # Clear stale reference so app.state.outbox_dispatcher_task never
    # points at a completed/cancelled task after shutdown.
    app.state.outbox_dispatcher_task = None
    logger.info("OutboxDispatcher stopped")


async def _setup_messenger_app_state(
    app,
) -> tuple["Pool | None", "object | None"]:
    """Wire ``app.state.{db_pool, redis, paseto_key_hex}`` for the messenger v1 API.

    The messenger router's dependencies (``messenger/api/v1/deps.py``) and
    its sub-routers (``channels``, ``messages``, ``users``) read these
    three slots off ``app.state``. Tests preset them via ``messenger_app``
    fixture; production previously had no equivalent wiring, leaving every
    messenger request 500/AttributeError. This helper plugs the gap.

    Each slot is independently tolerant of missing env vars: an unset env
    var is logged at INFO and the slot is left untouched (so existing
    test fixtures that pre-populate ``app.state.redis`` keep working).

    Returns ``(api_pool, redis_client)`` so the caller can clean them up
    on shutdown.
    """
    # PASETO key — required by deps.get_current_user and auth router.
    key_hex = os.environ.get("BREADMIND_MESSENGER_PASETO_KEY_HEX")
    if key_hex:
        app.state.paseto_key_hex = key_hex
        logger.info("messenger PASETO key configured on app.state")
    else:
        logger.info(
            "BREADMIND_MESSENGER_PASETO_KEY_HEX not set; "
            "messenger auth endpoints will reject requests"
        )

    # Dedicated asyncpg pool for messenger API request handlers. Kept
    # separate from the dispatcher pool so the dispatcher's LISTEN
    # connection (long-lived) cannot starve handler queries.
    api_pool = None
    try:
        api_pool = await acquire_pg_pool()
        app.state.db_pool = api_pool
        logger.info("messenger db_pool configured on app.state")
    except DatabaseUrlNotSet as e:
        logger.info(
            "BREADMIND_DB_URL/DATABASE_URL not set; messenger db_pool unavailable: %s",
            e,
        )

    # Redis client — backs OutboxDispatcher pub/sub, VisibleChannelsCache,
    # and IdempotencyStore. Use a fresh client (not shared with any other
    # subsystem) so its lifecycle matches the lifespan exactly.
    redis_client = None
    redis_url = os.environ.get("BREADMIND_REDIS_URL")
    if redis_url:
        try:
            import redis.asyncio as aioredis  # local import — keep cold-start light

            redis_client = aioredis.from_url(redis_url)
            await redis_client.ping()
            app.state.redis = redis_client
            logger.info("redis client configured on app.state")
        except Exception as e:  # noqa: BLE001 - tolerant by design
            logger.warning(
                "redis client init failed (%s); messenger pub/sub features disabled",
                e,
            )
            if redis_client is not None:
                try:
                    await redis_client.aclose()
                except Exception:  # noqa: BLE001
                    pass
            redis_client = None
    else:
        logger.info(
            "BREADMIND_REDIS_URL not set; messenger pub/sub features disabled"
        )

    return api_pool, redis_client


async def _teardown_messenger_app_state(
    api_pool: "Pool | None",
    redis_client: "object | None",
) -> None:
    """Best-effort close of resources created by ``_setup_messenger_app_state``."""
    if redis_client is not None:
        try:
            await redis_client.aclose()
        except Exception:  # noqa: BLE001
            logger.warning("redis client close failed", exc_info=True)
    if api_pool is not None:
        try:
            await api_pool.close()
        except Exception:  # noqa: BLE001
            logger.warning("messenger api pool close failed", exc_info=True)


@asynccontextmanager
async def lifespan(app):
    """FastAPI lifespan: migrate -> wire app.state -> start dispatcher -> yield -> cancel.

    Order:
      1. Run alembic migrations (gated by ``BREADMIND_AUTO_MIGRATE``).
      2. Wire ``app.state.{db_pool, redis, paseto_key_hex}`` for the
         messenger v1 API (each slot independently tolerant of missing
         env vars).
      3. Start :class:`OutboxDispatcher` as a background task (gated by
         ``BREADMIND_OUTBOX_DISPATCHER_ENABLED`` AND availability of
         ``BREADMIND_DB_URL`` AND ``app.state.redis``).
      4. Yield control to the app.
      5. On shutdown: cancel dispatcher, close dispatcher PG pool,
         close messenger api pool + redis client.

    No-DB / no-Redis tolerance: when env vars are missing, each subsystem
    skips with an INFO log. This keeps unit tests that boot the app via
    ``TestClient`` working without a real Postgres/Redis stack.
    """
    await maybe_run_migration()
    api_pool, redis_client = await _setup_messenger_app_state(app)
    pool, task = await _maybe_start_dispatcher(app)
    try:
        yield
    finally:
        await _stop_dispatcher(app, pool, task)
        await _teardown_messenger_app_state(api_pool, redis_client)
