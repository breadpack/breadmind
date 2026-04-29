"""Concurrency-safe alembic runner with PG advisory lock.

The advisory lock (LOCK_ID = 0x4D4947 / 'MIG' as ASCII) prevents two
processes (e.g., two uvicorn workers, or CLI + lifespan) from invoking
alembic concurrently. The lock is held for the duration of the migration
and released on completion or failure.

Shared by ``breadmind migrate`` (Click CLI in ``breadmind.cli.migrate``)
and the FastAPI lifespan auto-migrate hook in ``breadmind.web.lifespan``
so both code paths use the same locking + alembic invocation.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Final

import psycopg
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

logger = logging.getLogger(__name__)


class DatabaseUrlNotSet(RuntimeError):
    """Raised when neither ``BREADMIND_DB_URL`` nor ``DATABASE_URL`` is set.

    Typed sentinel so callers (e.g., the FastAPI lifespan auto-migrate hook)
    can distinguish a missing-DB-URL skip from any other RuntimeError without
    relying on string matching.
    """


# Advisory lock identifier — ASCII bytes for "MIG". Keeping it documented
# and centralized so any concurrent migration logic uses the same id.
LOCK_ID: Final[int] = 0x4D4947  # ASCII 'MIG'

# Migrations live next to this module under ``storage/migrations``.
_MIGRATIONS_DIR: Final[Path] = Path(__file__).resolve().parent / "migrations"


def _normalize_db_url(url: str) -> str:
    """Return a libpq-friendly DSN.

    psycopg / libpq accept ``postgresql://`` and ``postgres://`` but not
    SQLAlchemy's driver-qualified scheme like ``postgresql+psycopg2://``.
    Strip the driver suffix when present so callers can pass either form.
    """
    if url.startswith("postgresql+"):
        scheme_end = url.index("://")
        return f"postgresql{url[scheme_end:]}"
    return url


def _db_url() -> str:
    """Resolve database URL from env.

    Prefers ``BREADMIND_DB_URL`` (the messenger-m2 plan's canonical name),
    falls back to ``DATABASE_URL`` so existing operational tooling (and
    the rest of the BreadMind codebase) keeps working without a forced
    rename. Raises ``DatabaseUrlNotSet`` if neither is set so callers can
    distinguish this case from other configuration/runtime failures.
    """
    url = os.environ.get("BREADMIND_DB_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise DatabaseUrlNotSet(
            "BREADMIND_DB_URL (or DATABASE_URL) not set; cannot run migrations"
        )
    return url


def _alembic_cfg() -> AlembicConfig:
    """Build an alembic Config bound to the bundled migrations directory.

    BreadMind ships migrations programmatically (no ``alembic.ini`` on
    disk), so we construct a Config object and set ``script_location``
    explicitly. ``sqlalchemy.url`` is set from the env-resolved DSN so
    alembic's runtime can connect.
    """
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", _db_url())
    return cfg


def _wait_lock(conn: psycopg.Connection) -> None:
    """Block until the advisory lock is acquired."""
    conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))


def _release_lock(conn: psycopg.Connection) -> None:
    """Release the advisory lock."""
    conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))


def _with_lock(fn):
    """Run ``fn(cfg)`` while holding the migration advisory lock.

    If ``fn`` raises and the connection is unhealthy at finally-time,
    ``_release_lock`` itself can raise — which would mask the original
    error. PostgreSQL releases session-scoped advisory locks automatically
    when the connection closes, so swallowing an unlock failure here is
    safe and lets the real exception propagate.
    """
    cfg = _alembic_cfg()
    dsn = _normalize_db_url(_db_url())
    with psycopg.connect(dsn, autocommit=True) as conn:
        _wait_lock(conn)
        try:
            return fn(cfg)
        finally:
            try:
                _release_lock(conn)
            except Exception:
                logger.warning(
                    "advisory lock release failed (session-end will release)",
                    exc_info=True,
                )


def run_upgrade(rev: str = "head") -> str:
    """Apply migrations up to ``rev`` (default: head). Returns new revision."""

    def _run(cfg: AlembicConfig) -> str:
        alembic_command.upgrade(cfg, rev)
        return current_head()

    return _with_lock(_run)


def run_downgrade(rev: str) -> str:
    """Roll the database back to ``rev``. Returns the new revision."""

    def _run(cfg: AlembicConfig) -> str:
        alembic_command.downgrade(cfg, rev)
        return current_head()

    return _with_lock(_run)


def run_stamp(rev: str) -> None:
    """Force-mark the database at ``rev`` without running migrations."""

    def _run(cfg: AlembicConfig) -> None:
        alembic_command.stamp(cfg, rev)

    _with_lock(_run)


def current_head() -> str:
    """Return current DB revision (read-only; no advisory lock).

    Reads ``alembic_version.version_num`` directly via psycopg rather than
    handing the raw psycopg connection to ``alembic.MigrationContext.configure``
    — alembic's ``configure`` requires a SQLAlchemy connection (it
    immediately reads ``connection.dialect``) and silently fails with an
    AttributeError on raw DBAPI connections.
    """
    dsn = _normalize_db_url(_db_url())
    with psycopg.connect(dsn, autocommit=True) as conn:
        try:
            row = conn.execute(
                "SELECT version_num FROM alembic_version LIMIT 1",
            ).fetchone()
        except psycopg.errors.UndefinedTable:
            # Fresh DB — no migrations applied yet.
            return "(empty)"
        return row[0] if row else "(empty)"


def pending_count() -> int:
    """Count migrations between current DB revision and script head."""
    cfg = _alembic_cfg()
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    cur = current_head()
    if cur == "(empty)":
        return len(list(script.walk_revisions()))
    if head is None or cur == head:
        return 0
    revs = list(script.iterate_revisions(head, cur))
    return len(revs)
