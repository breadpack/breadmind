"""Database migration manager using Alembic.

Provides a programmatic interface to Alembic for running, generating,
and inspecting database migrations without requiring an alembic.ini file.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


@dataclass
class MigrationConfig:
    """Configuration for the migration system."""

    database_url: str = ""
    migrations_dir: str = field(default_factory=lambda: str(_MIGRATIONS_DIR))

    def __post_init__(self) -> None:
        if not self.database_url:
            self.database_url = os.environ.get("DATABASE_URL", "")


def _asyncpg_to_sqlalchemy(dsn: str) -> str:
    """Convert an asyncpg-style DSN to a SQLAlchemy-compatible URL.

    asyncpg uses ``postgresql://...`` which is the same as SQLAlchemy's
    default psycopg2 dialect. This helper ensures the scheme is correct
    for synchronous SQLAlchemy usage (``postgresql+psycopg2://``).
    If the URL already contains ``+`` (e.g. ``postgresql+asyncpg://``),
    replace the driver portion with ``psycopg2``.
    """
    if dsn.startswith("postgresql+"):
        # Replace any async driver with psycopg2
        scheme_end = dsn.index("://")
        return f"postgresql+psycopg2{dsn[scheme_end:]}"
    if dsn.startswith("postgresql://"):
        return dsn.replace("postgresql://", "postgresql+psycopg2://", 1)
    if dsn.startswith("postgres://"):
        return dsn.replace("postgres://", "postgresql+psycopg2://", 1)
    return dsn


class Migrator:
    """High-level interface for managing database migrations."""

    def __init__(self, config: MigrationConfig | None = None) -> None:
        self._config = config or MigrationConfig()
        self._alembic_cfg = self._build_alembic_config()

    def _build_alembic_config(self) -> AlembicConfig:
        """Create an Alembic Config object programmatically."""
        cfg = AlembicConfig()
        cfg.set_main_option(
            "script_location", self._config.migrations_dir,
        )
        if self._config.database_url:
            sa_url = _asyncpg_to_sqlalchemy(self._config.database_url)
            cfg.set_main_option("sqlalchemy.url", sa_url)
        return cfg

    @property
    def migrations_dir(self) -> str:
        return self._config.migrations_dir

    @property
    def script_directory(self) -> ScriptDirectory:
        return ScriptDirectory.from_config(self._alembic_cfg)

    # ── Query ────────────────────────────────────────────────────────

    def current_revision(self) -> str | None:
        """Return the current database revision, or None if not stamped."""
        from alembic.runtime.migration import MigrationContext
        from sqlalchemy import create_engine

        sa_url = _asyncpg_to_sqlalchemy(self._config.database_url)
        engine = create_engine(sa_url)
        try:
            with engine.connect() as conn:
                ctx = MigrationContext.configure(conn)
                return ctx.get_current_revision()
        finally:
            engine.dispose()

    def check(self) -> bool:
        """Return True if the database is at the latest revision."""
        current = self.current_revision()
        head = self.script_directory.get_current_head()
        return current == head

    def history(self) -> list[dict]:
        """Return the full migration history (oldest first)."""
        scripts = self.script_directory
        result: list[dict] = []
        for sc in scripts.walk_revisions():
            result.append({
                "revision": sc.revision,
                "down_revision": sc.down_revision,
                "description": sc.doc or "",
                "path": sc.path,
            })
        # walk_revisions returns newest-first; reverse for chronological order
        result.reverse()
        return result

    # ── Mutate ───────────────────────────────────────────────────────

    def upgrade(self, revision: str = "head") -> None:
        """Run upgrade migrations up to *revision* (default: head)."""
        logger.info("Running migrations upgrade to %s", revision)
        command.upgrade(self._alembic_cfg, revision)
        logger.info("Migration upgrade complete")

    def downgrade(self, revision: str) -> None:
        """Downgrade the database to *revision*."""
        logger.info("Running migrations downgrade to %s", revision)
        command.downgrade(self._alembic_cfg, revision)
        logger.info("Migration downgrade complete")

    def generate(self, message: str) -> str:
        """Auto-generate a new migration file. Returns the revision ID."""
        logger.info("Generating new migration: %s", message)
        rev = command.revision(
            self._alembic_cfg,
            message=message,
            autogenerate=False,
        )
        rev_id = rev.revision if rev else "unknown"
        logger.info("Generated migration %s", rev_id)
        return rev_id

    def stamp(self, revision: str = "head") -> None:
        """Stamp the database with a revision without running migrations.

        Useful for marking an existing database as up-to-date when
        tables were already created by the legacy _migrate() method.
        """
        logger.info("Stamping database at revision %s", revision)
        command.stamp(self._alembic_cfg, revision)


def run_migration_command(cmd: str, args: list[str] | None = None) -> None:
    """CLI entry point for migration commands.

    Parameters
    ----------
    cmd:
        One of: upgrade, downgrade, history, check, generate, stamp
    args:
        Additional arguments (e.g. revision for downgrade, message for generate).
    """
    args = args or []
    migrator = Migrator()

    if not migrator._config.database_url:
        print("Error: DATABASE_URL is not set. "
              "Set it as an environment variable or in config.")
        return

    if cmd == "upgrade":
        revision = args[0] if args else "head"
        migrator.upgrade(revision)
        print(f"Upgraded to {revision}")

    elif cmd == "downgrade":
        if not args:
            print("Error: downgrade requires a target revision")
            return
        migrator.downgrade(args[0])
        print(f"Downgraded to {args[0]}")

    elif cmd == "history":
        entries = migrator.history()
        if not entries:
            print("No migrations found.")
            return
        for entry in entries:
            marker = ""
            try:
                current = migrator.current_revision()
                if entry["revision"] == current:
                    marker = " (current)"
            except Exception:
                pass
            print(f"  {entry['revision']}{marker}: {entry['description']}")

    elif cmd == "check":
        try:
            up_to_date = migrator.check()
        except Exception as e:
            print(f"Error checking migration status: {e}")
            return
        if up_to_date:
            print("Database is up to date.")
        else:
            current = migrator.current_revision()
            head = migrator.script_directory.get_current_head()
            print(f"Database is NOT up to date. Current: {current}, Head: {head}")

    elif cmd == "generate":
        if not args:
            print("Error: generate requires a message")
            return
        message = " ".join(args)
        rev_id = migrator.generate(message)
        print(f"Generated migration: {rev_id}")

    elif cmd == "stamp":
        revision = args[0] if args else "head"
        migrator.stamp(revision)
        print(f"Stamped database at {revision}")

    else:
        print(f"Unknown migration command: {cmd}")
        print("Available: upgrade, downgrade, history, check, generate, stamp")
