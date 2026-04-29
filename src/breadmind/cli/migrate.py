"""breadmind migrate — alembic wrapper with PG advisory lock support.

Subcommands:
    up                Apply all pending migrations to head
    down N            Roll back N migrations
    status            Show current head + pending count
    stamp <revision>  Force-mark database at revision

The actual concurrency-safe migration runner lives in
``breadmind.storage.migrate_runner`` so the FastAPI lifespan auto-migrate
hook and this CLI share the same code path (advisory lock + alembic).
"""
from __future__ import annotations

import sys

import click

from breadmind.storage.migrate_runner import (
    current_head,
    pending_count,
    run_downgrade,
    run_stamp,
    run_upgrade,
)


@click.group(name="migrate", help="Database migration commands (alembic wrapper).")
def migrate() -> None:
    """Migration command group."""


@migrate.command("up", help="Apply all pending migrations to head (upgrade).")
def up_cmd() -> None:
    """Run ``alembic upgrade head`` under the advisory lock."""
    try:
        rev = run_upgrade("head")
        click.echo(f"Migrated to: {rev}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@migrate.command("down", help="Roll back N migrations.")
@click.argument("steps", type=int)
def down_cmd(steps: int) -> None:
    """Run ``alembic downgrade -N`` under the advisory lock."""
    try:
        rev = run_downgrade(f"-{steps}")
        click.echo(f"Rolled back to: {rev}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@migrate.command("status", help="Show current alembic head and pending count.")
def status_cmd() -> None:
    """Print the current DB revision and number of pending migrations."""
    try:
        head = current_head()
        pending = pending_count()
        click.echo(f"Current head: {head}")
        click.echo(f"Pending migrations: {pending}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@migrate.command("stamp", help="Force-mark database at the given revision.")
@click.argument("revision")
def stamp_cmd(revision: str) -> None:
    """Run ``alembic stamp <revision>`` under the advisory lock."""
    try:
        run_stamp(revision)
        click.echo(f"Stamped at: {revision}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
