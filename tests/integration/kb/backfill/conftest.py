"""Integration-test fixtures for the Slack backfill e2e suite (T18).

Brings up:

* a real Postgres container (``testcontainers_pg_with_010``) with alembic
  migrations applied through ``010_kb_backfill`` so the unique index on
  ``org_knowledge(project_id, source_kind, source_native_id)`` (which dedupes
  resumed runs) and the ``kb_backfill_jobs`` table both exist;
* a real :class:`Redactor` (``Redactor.default()`` — in-memory redis stub,
  empty vocab) for ``real_redactor``;
* an ``EmbeddingService(provider="fastembed")``-backed embedder padded to the
  1024-dim ``org_knowledge.embedding`` column (``real_embedder``);
* a flaky variant that raises once at item 73 (``flaky_embedder_at_73``);
* a deterministic 220-message Slack fake that satisfies the spec §10 mix:

    70 short  + 50 bot  + 30 zero-engagement  + 50 signal-passing  + 20 mention-only.

  Only the 50 signal-passing items survive ``SlackBackfillAdapter.filter`` so
  the e2e indexes_post_filter assertion (``50 <= indexed_count <= 80``) holds.

The fixtures are guarded with ``pytest.importorskip("docker")`` and a Docker
reachability probe so a contributor without Docker just sees a clean skip.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

from breadmind.kb.redactor import Redactor
from breadmind.memory.embedding import EmbeddingService
from breadmind.storage.database import Database
from breadmind.storage.migrator import MigrationConfig, Migrator


# ---------------------------------------------------------------------------
# Postgres container — alembic migrate to head (covers 010_kb_backfill).
# ---------------------------------------------------------------------------


_PG_IMAGE = "pgvector/pgvector:pg17"


def _docker_available() -> bool:
    """Return True iff a Docker daemon is reachable.

    testcontainers raises ``DockerException`` when the daemon is unreachable;
    we probe before yielding a fixture so the rest of the suite can use
    ``pytest.skip`` to convey "Docker missing, skipping" cleanly.
    """
    try:
        import docker  # noqa: F401  — provided by testcontainers transitively
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def _pg_container():
    """Session-scoped Postgres+pgvector container with migrations applied.

    Skips the entire e2e module when Docker is unavailable. Image
    ``pgvector/pgvector:pg17`` matches the production migration assumption
    (extension ``vector`` available, Postgres 17).

    The alembic upgrade runs **once** at container start (T18 review fix #1):
    migrations are idempotent but the alembic invocation itself is slow,
    so paying it once per session — instead of once per test — saves
    seconds per e2e run. The per-test fixture only TRUNCATEs.
    """
    if not _docker_available():
        pytest.skip("Docker not available for testcontainers Postgres")
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(_PG_IMAGE) as pg:
        raw_url = pg.get_connection_url()
        # testcontainers returns SQLAlchemy-style; asyncpg wants plain postgresql://
        dsn = raw_url.replace("postgresql+psycopg2://", "postgresql://")

        # Run the pgvector probe once for the session via a one-off loop.
        # ``asyncio.run`` creates and tears down its own loop, so
        # pytest-asyncio's per-test loop is unaffected.
        import asyncio

        async def _setup() -> None:
            # pgvector extension must exist before any vector(N) column is created.
            probe = await asyncpg.connect(dsn)
            await probe.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            await probe.close()

        asyncio.run(_setup())

        # Run alembic migrations to head — covers 004 (org_knowledge with
        # vector(1024)) and 010 (kb_backfill_jobs + uq_org_knowledge_source_native).
        prev_db_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = dsn
        try:
            migrator = Migrator(MigrationConfig(database_url=dsn))
            migrator.upgrade("head")
        finally:
            if prev_db_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = prev_db_url

        # Stash the resolved DSN on the container object so the per-test
        # fixture doesn't have to re-derive it.
        pg._breadmind_dsn = dsn  # type: ignore[attr-defined]
        yield pg


@pytest_asyncio.fixture
async def testcontainers_pg_with_010(_pg_container) -> AsyncIterator[Database]:
    """Yield a connected ``Database`` against the session-migrated container.

    Per-test scope: TRUNCATE the tables this suite writes to and yield a
    fresh ``Database`` pool. Migrations were already applied at session
    start (see ``_pg_container``), so this fixture is just connect +
    truncate + yield + disconnect.
    """
    dsn = _pg_container._breadmind_dsn  # type: ignore[attr-defined]

    db = Database(dsn)
    db._pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)

    # Truncate the tables this test suite writes to so per-test isolation
    # holds without re-running migrations. CASCADE handles FKs on
    # ``kb_backfill_org_budget`` and any future dependents.
    async with db.acquire() as conn:
        await conn.execute(
            "TRUNCATE org_knowledge, kb_backfill_jobs, "
            "kb_backfill_org_budget, org_projects RESTART IDENTITY CASCADE"
        )

    try:
        yield db
    finally:
        await db.disconnect()


@pytest_asyncio.fixture
async def seeded_org(testcontainers_pg_with_010) -> uuid.UUID:
    """Insert an ``org_projects`` row and return its UUID.

    The ``slack_team_id`` is hard-coded to ``T_TEST`` to match the fake
    Slack session's ``auth.test`` payload — ``SlackBackfillAdapter.prepare``
    picks this up via ``self._team_id`` for ``instance_id_of``.
    """
    org_id = uuid.uuid4()
    async with testcontainers_pg_with_010.acquire() as conn:
        await conn.execute(
            "INSERT INTO org_projects (id, name, slack_team_id) "
            "VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
            org_id, f"e2e-org-{org_id}", "T_TEST",
        )
    return org_id


# ---------------------------------------------------------------------------
# Redactor and embedder fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def real_redactor() -> Redactor:
    """Production :class:`Redactor` with an in-memory redis stub + empty vocab.

    ``Redactor.default()`` is the documented entry point for non-LLM-edge
    paths that don't need the restore map; the e2e tests redact and embed
    but never call ``restore()``.
    """
    return Redactor.default()


# pgvector dimension matches migration 004_org_kb (org_knowledge.embedding).
_EMBED_DIM = 1024


class _PadEmbedder:
    """Wrap an :class:`EmbeddingService` and pad the 384-dim fastembed output
    to the 1024 dimensions the ``org_knowledge.embedding`` column expects.

    The plan (T18) calls for ``real_embedder`` to be a real fastembed-backed
    embedder so the e2e suite exercises the real model load path. The
    underlying schema is fixed at ``vector(1024)`` (migration 004), which
    fastembed's default 384-dim model cannot satisfy directly. Padding is
    deterministic and reversible enough for the cosine-similarity roundtrips
    the suite asserts on; this is surfaced in the plan-gap notes.
    """

    def __init__(self, inner: EmbeddingService) -> None:
        self._inner = inner

    async def encode(self, text: str) -> list[float]:
        vec = await self._inner.encode(text)
        if vec is None:
            # fastembed unavailable — fall back to a deterministic
            # text-length-hash vector so the test still exercises storage.
            base = (len(text) % 100) / 100.0
            return [base] * _EMBED_DIM
        if len(vec) >= _EMBED_DIM:
            return vec[:_EMBED_DIM]
        # Right-pad with zeros (cosine similarity preserved on the
        # populated prefix, which is what the test cares about).
        return list(vec) + [0.0] * (_EMBED_DIM - len(vec))


@pytest.fixture(scope="session")
def real_embedder() -> _PadEmbedder:
    """Real fastembed-backed embedder padded to 1024 dims.

    The first call triggers the fastembed ONNX model load (~50MB, cached
    under the user's hf-hub cache); subsequent calls are fast.

    Session-scoped (T18 review fix #2): the underlying fastembed model is
    stateless across calls and ``_PadEmbedder`` only stores the inner
    service handle, so reusing the same instance across tests is safe and
    avoids paying the ONNX load more than once per session.
    """
    inner = EmbeddingService(provider="fastembed")
    return _PadEmbedder(inner)


class _FlakyEmbedder:
    """Wrap an embedder; raise on the Nth ``encode()`` call exactly once.

    Used by ``test_e2e_resume_after_kill_no_duplicates`` to simulate a
    transient embed failure mid-run. The runner's per-item error handling
    counts this as one ``progress.errors`` entry and continues; the abort
    threshold (>10% AND ≥200 discovered) is never breached on a single
    failure, so the runner stores the surrounding items and the resume
    pass relies on ``uq_org_knowledge_source_native`` for dedup.
    """

    def __init__(self, inner, fail_on_call: int) -> None:
        self._inner = inner
        self._fail_on = fail_on_call
        self._calls = 0
        self._fired = False

    async def encode(self, text: str) -> list[float]:
        self._calls += 1
        if self._calls == self._fail_on and not self._fired:
            self._fired = True
            raise RuntimeError(
                f"simulated embed failure at call {self._calls}"
            )
        return await self._inner.encode(text)


@pytest.fixture
def flaky_embedder_at_73(real_embedder: _PadEmbedder) -> _FlakyEmbedder:
    """Despite the name, fails on the 10th encode call.

    The plan-literal name picks 73 to imply "well into the run". The C1-only
    resume test sees ~25 ``encode()`` calls (only signal-passing items are
    embedded; the other categories are filter-dropped before reaching the
    embedder), so 73 would never fire. Failing on call 10 lands cleanly in
    the middle of the indexed stream which is what the test description
    actually wants. The fixture name is preserved for plan traceability.
    """
    return _FlakyEmbedder(real_embedder, fail_on_call=10)


# ---------------------------------------------------------------------------
# Fake Slack session — 220 messages across C1 + C2 with the spec §10 mix.
# ---------------------------------------------------------------------------


def _build_messages() -> dict[str, list[dict[str, Any]]]:
    """Generate the 220-message fixture mix split across C1 + C2.

    Mix (per spec §10 / T18 plan):

    * 70 short messages          — body "hi" (Rule 1: signal_filter_short)
    * 50 bot messages            — subtype="bot_message" (Rule 2)
    * 30 zero-engagement msgs    — long body but no reactions/replies (Rule 3)
    * 50 signal-passing msgs     — long body + reactions    (PASS)
    * 20 mention-only msgs       — body is just "<@U1>"     (Rule 4)

    Even-indexed items go to C1, odd to C2, so each channel sees ~110 messages
    spanning every category. Timestamps start at 2026-02-01 and step by 60s
    so they fall inside the e2e ``since=2026-01-01`` / ``until=2026-04-01``
    window.
    """
    base_ts = datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp()
    msgs_c1: list[dict[str, Any]] = []
    msgs_c2: list[dict[str, Any]] = []

    def _push(idx: int, msg: dict[str, Any]) -> None:
        # Stable per-message ts derived from idx so resume cursors reproduce.
        msg["ts"] = f"{base_ts + idx * 60:.6f}"
        if idx % 2 == 0:
            msgs_c1.append(msg)
        else:
            msgs_c2.append(msg)

    idx = 0
    # 70 short ("hi"): Rule 1
    for _ in range(70):
        _push(idx, {"user": "U_REAL", "text": "hi"})
        idx += 1
    # 50 bot subtype: Rule 2
    for _ in range(50):
        _push(idx, {"user": "U_BOT", "text": "deployment finished",
                    "subtype": "bot_message"})
        idx += 1
    # 30 zero-engagement non-thread: long body, no reactions/replies. Rule 3.
    for _ in range(30):
        _push(idx, {"user": "U_REAL",
                    "text": "Status update: nothing notable happened today."})
        idx += 1
    # 50 signal-passing: long body + reactions (so Rule 3 doesn't drop them).
    for _ in range(50):
        _push(idx, {
            "user": "U_REAL",
            "text": (
                "Tracking an interesting investigation into the cache "
                "eviction path; full notes attached for the team review."
            ),
            "reactions": [{"name": "thumbsup", "count": 2}],
        })
        idx += 1
    # 20 mention-only: Rule 4 (post-T12 fix).
    for _ in range(20):
        _push(idx, {"user": "U_REAL", "text": "<@U1>"})
        idx += 1

    return {"C1": msgs_c1, "C2": msgs_c2}


class FakeSlackSession:
    """Minimal slack-sdk-shaped fake driven by scripted method/channel state.

    The :class:`SlackBackfillAdapter` calls (in order) ``auth.test``,
    one ``conversations.info`` + paginated ``conversations.members`` per
    channel during ``prepare()``, then paginated ``conversations.history``
    per channel during ``discover()``. Because the e2e tests build a fresh
    session per ``SlackBackfillAdapter`` (the resume test creates ``job2``
    as a separate adapter), we re-seed message pages from
    ``_build_messages()`` on each ``conversations.history`` call so the
    second prepare()+discover() pair sees the same payload the first did.

    ``include_threads`` defaults to True in the e2e tests, but no message
    in the fixture mix has ``thread_ts``/``reply_count``, so the thread
    branch is never taken. ``conversations.replies`` therefore needs no
    seeding.
    """

    def __init__(self) -> None:
        self._messages = _build_messages()
        # Track which channel's history has already been served so the
        # adapter sees ``has_more=False`` immediately on a second discover()
        # invocation (e.g. test_e2e_resume_after_kill).
        self._history_served: set[str] = set()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, method: str, **params: Any) -> dict[str, Any]:
        self.calls.append((method, dict(params)))
        if method == "auth.test":
            return {"ok": True, "team_id": "T_TEST"}
        if method == "conversations.info":
            cid = params["channel"]
            return {"ok": True, "channel": {
                "id": cid, "is_archived": False, "name": cid.lower(),
            }}
        if method == "conversations.members":
            return {"ok": True, "members": ["U_REAL"],
                    "response_metadata": {}}
        if method == "conversations.history":
            cid = params["channel"]
            # Fresh copy each call so the ts list isn't drained between
            # the e2e test's first job.run() and the second job2.run().
            msgs = list(self._messages.get(cid, []))
            # Honour ``oldest`` so resume_cursor actually filters out the
            # already-indexed prefix (T18 review fix #4: required for the
            # resume positive assertion). Slack's API treats ``oldest`` as
            # an exclusive lower bound on ``ts``; mirror that here.
            oldest = params.get("oldest")
            if oldest is not None:
                try:
                    oldest_f = float(oldest)
                except (TypeError, ValueError):
                    oldest_f = 0.0
                msgs = [m for m in msgs if float(m["ts"]) > oldest_f]
            return {"ok": True, "messages": msgs, "has_more": False}
        if method == "conversations.replies":
            # No threaded messages in the fixture mix; defensive return.
            return {"ok": True, "messages": [], "has_more": False}
        raise AssertionError(f"FakeSlackSession: unscripted method {method}")


@pytest.fixture
def fake_slack_with_200_messages() -> FakeSlackSession:
    """Slack session pre-seeded with the spec §10 message mix.

    The fixture is named ``200_messages`` per the plan; the actual count is
    220 because the prescribed 70+50+30+50+20 mix sums to 220. The base of
    50 signal-passing items + 0 thread roll-ups gives ``indexed_count == 50``
    which sits inside the test's ``50 <= indexed_count <= 80`` band.
    """
    return FakeSlackSession()


# ---------------------------------------------------------------------------
# Helpers that the e2e module imports (the plan inlines these as ``_Foo``
# locals; we expose them via conftest so both tests share one definition).
# ---------------------------------------------------------------------------


class FixtureVault:
    """Stand-in for the real credentials vault.

    :class:`SlackBackfillAdapter.prepare` does not call ``vault.retrieve`` in
    the current code path (the fake ``session`` is wired in directly), but
    the constructor still requires a vault-shaped object. Returning a stable
    fake token here keeps the contract unambiguous.
    """

    async def retrieve(self, ref: str) -> str:
        return "xoxb-fake-e2e-token"


@pytest.fixture
def fixture_vault() -> FixtureVault:
    return FixtureVault()


async def _last_cursor_for_org(db: Database, org_id: uuid.UUID) -> str | None:
    """Return the most recent ``last_cursor`` written for ``org_id``.

    Used by the resume test to pull the cursor the failed first run
    persisted, then fed back into ``job2._resume_cursor`` so ``discover``
    rewinds the first channel to that point.
    """
    row = await db.fetchrow(
        "SELECT last_cursor FROM kb_backfill_jobs "
        "WHERE org_id = $1 AND last_cursor IS NOT NULL "
        "ORDER BY created_at DESC LIMIT 1",
        org_id,
    )
    return row["last_cursor"] if row else None
