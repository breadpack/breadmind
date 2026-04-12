"""hook_overrides table: hooks-v2 runtime override registry.

Revision ID: 003_hook_overrides
Revises: 002_flow_events
Create Date: 2026-04-12

Introduces the ``hook_overrides`` table used by hooks-v2 to persist
runtime overrides of hook configuration (enable/disable, priority,
tool pattern, config payload) independently from the source hook
definitions loaded from plugins and settings files.

Tables
------
hook_overrides
    One row per override keyed by ``id``. ``hook_id`` identifies the
    underlying hook being overridden; ``source`` records where the
    override originated (plugin id, user, etc.). ``config_json``
    carries the full override payload.
"""

from alembic import op

revision = "003_hook_overrides"
down_revision = "002_flow_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS hook_overrides (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            hook_id TEXT NOT NULL,
            source TEXT,
            event TEXT NOT NULL,
            type TEXT NOT NULL,
            tool_pattern TEXT,
            priority INTEGER NOT NULL DEFAULT 0,
            enabled BOOLEAN NOT NULL DEFAULT true,
            config_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS ix_hook_overrides_event
            ON hook_overrides (event);
        CREATE INDEX IF NOT EXISTS ix_hook_overrides_hook_id
            ON hook_overrides (hook_id);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS ix_hook_overrides_hook_id;
        DROP INDEX IF EXISTS ix_hook_overrides_event;
        DROP TABLE IF EXISTS hook_overrides CASCADE;
    """)
