"""E2E harness: Postgres via testcontainers + fakeredis + stubs."""
from __future__ import annotations

import pathlib

import asyncpg
import fakeredis.aioredis
import pytest
from testcontainers.postgres import PostgresContainer

_E2E_DIR = pathlib.Path(__file__).parent.resolve()


def pytest_collection_modifyitems(config, items):
    for item in items:
        try:
            pathlib.Path(item.path).resolve().relative_to(_E2E_DIR)
        except ValueError:
            continue
        item.add_marker(pytest.mark.e2e)


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer("pgvector/pgvector:pg17") as pg:
        yield pg


@pytest.fixture(scope="session")
def pg_dsn(pg_container) -> str:
    raw = pg_container.get_connection_url()
    return raw.replace("postgresql+psycopg2", "postgresql")


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations(pg_dsn):
    # This project keeps Alembic config programmatic (no repo-root alembic.ini).
    # Use the project's Migrator wrapper which points at
    # src/breadmind/storage/migrations.
    from breadmind.storage.migrator import MigrationConfig, Migrator

    migrator = Migrator(MigrationConfig(database_url=pg_dsn))
    migrator.upgrade("head")


@pytest.fixture(scope="session", autouse=True)
def _seed(pg_dsn, _apply_migrations):
    import subprocess
    subprocess.check_call(
        ["python", "scripts/seed_pilot_data.py", "--dsn", pg_dsn]
    )


@pytest.fixture(scope="session", autouse=True)
async def _ensure_e2e_schema_once(pg_dsn, _seed):
    """Install the E2E-only DDL bits that migrations skip.

    ``QueryPipeline.build_for_e2e`` lazy-installs this on first use via
    :func:`breadmind.kb.e2e_factories.ensure_e2e_schema`, but several
    tests execute ``INSERT ... ON CONFLICT (name)`` style DDL on
    ``org_projects`` *before* calling ``build_for_e2e``. Running the
    augmentation once at session start avoids test-order dependencies.
    """
    import asyncpg

    from breadmind.kb.e2e_factories import ensure_e2e_schema

    conn = await asyncpg.connect(dsn=pg_dsn)
    try:
        await ensure_e2e_schema(conn)
    finally:
        await conn.close()


@pytest.fixture
async def db(pg_dsn):
    conn = await asyncpg.connect(dsn=pg_dsn)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    try:
        yield r
    finally:
        await r.aclose()


@pytest.fixture
def slack():
    from tests.e2e.fixtures.slack import FakeSlackClient
    return FakeSlackClient()


@pytest.fixture
def llm():
    from tests.e2e.fixtures.llm import StubLLM
    return StubLLM()


@pytest.fixture(autouse=True)
def _reset_metrics():
    from prometheus_client import CollectorRegistry

    from breadmind.kb import metrics
    metrics._build_metrics(CollectorRegistry())


# ── long-running-monitoring E2E fixtures ────────────────────────────────

# Alias used by ``tests/e2e/test_long_running_monitoring.py`` so the test
# signature matches the plan verbatim while reusing the session-scoped
# Postgres container defined above.
@pytest.fixture(scope="session")
def postgres_container(pg_container):
    return pg_container


@pytest.fixture
async def breadmind_server(pg_dsn):
    """Spin up a real breadmind FastAPI app on a random localhost port.

    Wires the coding ``JobStore`` + ``LogBuffer`` against the testcontainers
    Postgres, resets the ``JobTracker`` singleton, and launches uvicorn in
    the current event loop so HTTP clients and CLI subprocesses can both
    reach it.

    Yields::

        {"url": "http://127.0.0.1:<port>", "api_key": "<token>",
         "store": JobStore, "tracker": JobTracker, "db": Database}

    Auth is left **disabled** (``AuthManager()`` with no credentials) so
    ``get_current_user`` returns the admin ``local`` user; subprocess CLI
    calls therefore don't need a valid X-API-Key to exercise the routes.
    An api_key is still generated and returned in case a future variant of
    this fixture wants to flip auth on.
    """
    import asyncio
    import secrets
    import socket

    from breadmind.coding.job_store import JobStore
    from breadmind.coding.job_tracker import JobTracker
    from breadmind.coding.log_buffer import LogBuffer
    from breadmind.storage.database import Database
    from breadmind.web import deps as web_deps
    from breadmind.web.app import WebApp
    from breadmind.web.auth import AuthManager

    # Reset tracker singleton so state from prior tests doesn't leak.
    JobTracker._instance = None

    db = Database(pg_dsn)
    await db.connect()

    auth = AuthManager()  # disabled — get_current_user -> local admin
    web_deps.set_auth_manager(auth)

    store = JobStore(db)
    tracker = JobTracker.get_instance()
    tracker.bind_store(store)
    buffer = LogBuffer(
        flush_fn=JobTracker.make_default_flush(store),
        size_threshold=10,
        time_threshold_s=0.2,
        per_phase_cap=1000,
    )
    tracker.bind_log_buffer(buffer)

    # Clean slate on coding tables so repeated runs don't collide on PKs.
    async with db.acquire() as conn:
        await conn.execute("DELETE FROM coding_jobs")

    wrapper = WebApp(auth=auth, database=db)
    # Coding routes read app.state.job_store for log lookups; in production
    # this is wired via an on_startup handler against a real DB pool, but
    # we've already built the store so attach it directly.
    wrapper.app.state.job_store = store

    # Pick a free port explicitly (uvicorn's port=0 doesn't readily expose
    # the bound port via config.servers on all versions).
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    from uvicorn import Config, Server

    config = Config(
        wrapper.app, host="127.0.0.1", port=port, log_level="warning",
        lifespan="on",
    )
    server = Server(config)
    server_task = asyncio.create_task(server.serve())

    # Wait for server to report started (with a hard timeout).
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.05)
    else:
        server.should_exit = True
        await server_task
        await db.disconnect()
        raise RuntimeError("uvicorn did not start within 10s")

    api_key = secrets.token_urlsafe(16)
    base_url = f"http://127.0.0.1:{port}"
    try:
        yield {
            "url": base_url,
            "api_key": api_key,
            "store": store,
            "tracker": tracker,
            "db": db,
        }
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=5.0)
        except (asyncio.TimeoutError, Exception):
            server_task.cancel()
            try:
                await server_task
            except Exception:
                pass
        try:
            await db.disconnect()
        except Exception:
            pass
        JobTracker._instance = None
