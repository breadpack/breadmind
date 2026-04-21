"""connector_configs: per-connector per-scope runtime configuration.

Revision ID: 006_connector_configs
Revises: 005_kb_p3_feedback
Create Date: 2026-04-21

Creates the ``connector_configs`` table that Celery Beat reads to
schedule ingestion sync runs. One row per (connector, scope_key);
settings is connector-specific JSON (e.g. Confluence base_url and
credential vault reference).
"""

from alembic import op

revision = "006_connector_configs"
down_revision = "005_kb_p3_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS connector_configs (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            connector   TEXT NOT NULL,
            project_id  UUID REFERENCES org_projects(id) ON DELETE CASCADE,
            scope_key   TEXT NOT NULL,
            settings    JSONB NOT NULL,
            enabled     BOOLEAN NOT NULL DEFAULT true,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (connector, scope_key)
        );

        CREATE INDEX IF NOT EXISTS idx_connector_configs_enabled
            ON connector_configs (connector, enabled)
            WHERE enabled = true;
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS idx_connector_configs_enabled;
        DROP TABLE IF EXISTS connector_configs CASCADE;
    """)
