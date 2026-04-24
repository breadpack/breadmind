"""Web test shared fixtures.

Re-exports KB fixtures so tests under ``tests/web/`` can use the same
Postgres container, seeded project, and fake Slack client as the KB tests.

pytest 8 discourages ``pytest_plugins`` in non-root conftest files, so we
import the fixture functions explicitly — each imported name becomes a
fixture scoped to this package.

Also defines lightweight fixtures (``web_app_client``, ``seeded_jobs``,
``seeded_jobs_with_logs``) used by tests that exercise the full FastAPI
stack via ``TestClient`` against ``breadmind.web.app.WebApp``.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from tests.kb.conftest import (  # noqa: F401
    db,
    fake_slack_client,
    pg_container,
    seeded_project,
)


@pytest.fixture
def web_app_client() -> TestClient:
    """Build a ``WebApp`` with auth enabled and a fresh ``JobTracker``.

    The ``AuthManager`` constructor derives ``enabled`` from
    ``bool(password_hash)`` so we only need to pass the hash. The
    module-level ``JobTracker._instance`` singleton is reset before and
    after each test so seeded rows from neighbouring tests don't leak.

    The TestClient is entered as a context manager so Starlette's
    :class:`anyio.from_thread.BlockingPortal` is created and FastAPI
    startup/shutdown events fire. That portal loop is what route
    handlers run on, so any asyncpg pool used from handlers must also
    live on that loop — see :func:`seeded_jobs_with_logs`.
    """
    from breadmind.coding.job_tracker import JobTracker
    from breadmind.web.app import WebApp
    from breadmind.web.auth import AuthManager

    # Reset the singleton so tests don't share state.
    JobTracker._instance = None

    auth = AuthManager(password_hash=AuthManager.hash_password("p"))
    app_wrapper = WebApp(
        message_handler=AsyncMock(return_value={"response": "ok", "agent": "test"}),
        auth=auth,
    )
    with TestClient(app_wrapper.app) as client:
        try:
            yield client
        finally:
            JobTracker._instance = None


@pytest.fixture
def seeded_jobs(web_app_client):
    """Seed two coding jobs owned by different users on the singleton tracker."""
    from breadmind.coding.job_tracker import JobTracker

    tracker = JobTracker.get_instance()
    tracker.create_job("alice-job-1", "p", "c", "x", user="alice", channel="")
    tracker.create_job("bob-job-1", "p", "c", "x", user="bob", channel="")
    return tracker


@pytest.fixture
def seeded_jobs_with_logs(web_app_client, seeded_jobs):
    """Seed ``alice-job-1`` with 20 log lines at ``step=1`` in Postgres.

    Postgres integration: probes ``TEST_DATABASE_URL`` /  ``DATABASE_URL``
    (same resolution as the shared ``test_db`` fixture) and skips the
    test if unreachable so a local run without Postgres doesn't blow up.

    Critical detail — asyncpg pools are bound to the loop that created
    them. The production route handler runs on the TestClient's portal
    loop; we therefore construct our ``asyncpg.Pool`` + :class:`JobStore`
    via ``web_app_client.portal.call(...)`` so every DB op (seeding here
    and fetching from the route) shares one loop.
    """
    import os
    from datetime import datetime, timezone

    import asyncpg

    from breadmind.coding.job_store import JobStore
    from breadmind.coding.job_tracker import JobTracker
    from breadmind.storage.database import Database
    from breadmind.storage.migrator import MigrationConfig, Migrator

    dsn = (
        os.environ.get("TEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or "postgresql://breadmind:breadmind_dev@localhost:5434/breadmind"
    )

    portal = web_app_client.portal

    async def _probe() -> None:
        conn = await asyncpg.connect(dsn, timeout=3)
        await conn.close()

    try:
        portal.call(_probe)
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"PostgreSQL not reachable at {dsn}: {exc}")

    # Run migrations once (sync). Idempotent on repeated test runs.
    Migrator(MigrationConfig(database_url=dsn)).upgrade("head")

    database = Database(dsn)

    async def _setup() -> JobStore:
        database._pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
        store = JobStore(database)
        # Clean slate on the coding tables so repeated runs don't collide
        # on ``(job_id, step, line_no)``.
        async with database.acquire() as conn:
            await conn.execute("DELETE FROM coding_jobs")
        # Parent job row first so phase/logs FKs are satisfied.
        await store.insert_job(
            job_id="alice-job-1",
            project="p",
            agent="c",
            prompt="x",
            user_name="alice",
            channel="",
            started_at=datetime.now(timezone.utc),
            status="running",
        )
        await store.insert_phases(
            "alice-job-1", [{"step": 1, "title": "phase1"}]
        )
        now = datetime.now(timezone.utc)
        batch = [(1, i, now, f"log line {i}") for i in range(1, 21)]
        await store.insert_log_batch("alice-job-1", batch)
        return store

    store = portal.call(_setup)

    tracker = JobTracker.get_instance()
    tracker.bind_store(store)
    # Bind store to app state so the route can find it — production wires
    # this via an ``@app.on_event("startup")`` handler in web/app.py.
    web_app_client.app.state.job_store = store

    try:
        yield store
    finally:
        async def _teardown() -> None:
            if database._pool is not None:
                await database._pool.close()

        try:
            portal.call(_teardown)
        except Exception:
            pass
