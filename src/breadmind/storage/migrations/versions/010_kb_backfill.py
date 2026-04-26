"""Backfill pipeline schema — org_knowledge provenance + jobs + per-org budget.

Revision ID: 010_kb_backfill
Revises: 009_episodic_org_id
Create Date: 2026-04-26
"""

from alembic import op

revision = "010_kb_backfill"
down_revision = "009_episodic_org_id"
branch_labels = None
depends_on = None


UPGRADE_SQL = """
ALTER TABLE org_knowledge
    ADD COLUMN IF NOT EXISTS source_kind         TEXT,
    ADD COLUMN IF NOT EXISTS source_native_id    TEXT,
    ADD COLUMN IF NOT EXISTS source_created_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS source_updated_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS parent_ref          TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_org_knowledge_source_native
    ON org_knowledge (project_id, source_kind, source_native_id)
    WHERE source_native_id IS NOT NULL AND superseded_by IS NULL;

CREATE INDEX IF NOT EXISTS ix_org_knowledge_source_created_at
    ON org_knowledge (project_id, source_created_at DESC)
    WHERE source_created_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_org_knowledge_source_updated_at
    ON org_knowledge (project_id, source_updated_at DESC)
    WHERE source_updated_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_org_knowledge_parent_ref
    ON org_knowledge (project_id, parent_ref)
    WHERE parent_ref IS NOT NULL;

CREATE TABLE IF NOT EXISTS kb_backfill_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES org_projects(id) ON DELETE CASCADE,
    source_kind     TEXT NOT NULL,
    source_filter   JSONB NOT NULL,
    instance_id     TEXT NOT NULL,
    since_ts        TIMESTAMPTZ NOT NULL,
    until_ts        TIMESTAMPTZ NOT NULL,
    dry_run         BOOLEAN NOT NULL,
    token_budget    BIGINT NOT NULL,
    status          TEXT NOT NULL,
    last_cursor     TEXT,
    progress_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    skipped_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    error           TEXT,
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_kb_backfill_org_status
    ON kb_backfill_jobs (org_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS kb_backfill_org_budget (
    org_id          UUID NOT NULL REFERENCES org_projects(id) ON DELETE CASCADE,
    period_month    DATE NOT NULL,
    tokens_used     BIGINT NOT NULL DEFAULT 0,
    tokens_ceiling  BIGINT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, period_month)
);
"""


DOWNGRADE_SQL = """
DROP TABLE IF EXISTS kb_backfill_org_budget;
DROP INDEX IF EXISTS ix_kb_backfill_org_status;
DROP TABLE IF EXISTS kb_backfill_jobs;
DROP INDEX IF EXISTS ix_org_knowledge_parent_ref;
DROP INDEX IF EXISTS ix_org_knowledge_source_updated_at;
DROP INDEX IF EXISTS ix_org_knowledge_source_created_at;
DROP INDEX IF EXISTS uq_org_knowledge_source_native;
ALTER TABLE org_knowledge
    DROP COLUMN IF EXISTS parent_ref,
    DROP COLUMN IF EXISTS source_updated_at,
    DROP COLUMN IF EXISTS source_created_at,
    DROP COLUMN IF EXISTS source_native_id,
    DROP COLUMN IF EXISTS source_kind;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
