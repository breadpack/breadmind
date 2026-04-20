"""org_kb tables: organization knowledge base + ACL + audit.

Revision ID: 004_org_kb
Revises: 003_hook_overrides
Create Date: 2026-04-20

Introduces the schema backing the Slack company KB feature (Phase 1):
tenancy/permissions (``org_projects``, ``org_project_members``,
``org_channel_map``), curated knowledge (``org_knowledge`` with
pgvector HNSW) + citations (``kb_sources``), the lead review queue
(``promotion_candidates``), connector cursors
(``connector_sync_state``), audit trail (``kb_audit_log``), and the
redaction vocabulary table (``redaction_vocab``).
"""

from alembic import op

revision = "004_org_kb"
down_revision = "003_hook_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE EXTENSION IF NOT EXISTS vector;

        CREATE TABLE IF NOT EXISTS org_projects (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name            TEXT NOT NULL,
            slack_team_id   TEXT NOT NULL,
            created_at      TIMESTAMPTZ DEFAULT now()
        );

        CREATE TABLE IF NOT EXISTS org_project_members (
            project_id      UUID REFERENCES org_projects(id) ON DELETE CASCADE,
            user_id         TEXT NOT NULL,
            role            TEXT NOT NULL,
            PRIMARY KEY (project_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS org_channel_map (
            channel_id      TEXT PRIMARY KEY,
            project_id      UUID REFERENCES org_projects(id),
            visibility      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS org_knowledge (
            id              BIGSERIAL PRIMARY KEY,
            project_id      UUID REFERENCES org_projects(id),
            title           TEXT NOT NULL,
            body            TEXT NOT NULL,
            category        TEXT NOT NULL,
            source_channel  TEXT,
            tags            TEXT[] DEFAULT '{}',
            embedding       vector(1024),
            promoted_from   TEXT,
            promoted_by     TEXT,
            promoted_at     TIMESTAMPTZ,
            revision        INT NOT NULL DEFAULT 1,
            superseded_by   BIGINT REFERENCES org_knowledge(id),
            created_at      TIMESTAMPTZ DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS idx_org_kn_project
            ON org_knowledge(project_id) WHERE superseded_by IS NULL;
        CREATE INDEX IF NOT EXISTS idx_org_kn_embedding
            ON org_knowledge USING hnsw (embedding vector_cosine_ops);

        CREATE TABLE IF NOT EXISTS kb_sources (
            id              BIGSERIAL PRIMARY KEY,
            knowledge_id    BIGINT REFERENCES org_knowledge(id) ON DELETE CASCADE,
            source_type     TEXT NOT NULL,
            source_uri      TEXT NOT NULL,
            source_ref      TEXT,
            captured_at     TIMESTAMPTZ DEFAULT now()
        );

        CREATE TABLE IF NOT EXISTS promotion_candidates (
            id                  BIGSERIAL PRIMARY KEY,
            project_id          UUID REFERENCES org_projects(id),
            extracted_from      TEXT NOT NULL,
            original_user       TEXT,
            proposed_title      TEXT,
            proposed_body       TEXT,
            proposed_category   TEXT,
            sources_json        JSONB,
            confidence          REAL,
            status              TEXT NOT NULL DEFAULT 'pending',
            reviewer            TEXT,
            reviewed_at         TIMESTAMPTZ,
            created_at          TIMESTAMPTZ DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS idx_promo_project_status
            ON promotion_candidates(project_id, status);

        CREATE TABLE IF NOT EXISTS connector_sync_state (
            id              BIGSERIAL PRIMARY KEY,
            connector       TEXT NOT NULL,
            scope_key       TEXT NOT NULL,
            project_id      UUID REFERENCES org_projects(id),
            last_cursor     TEXT,
            last_run_at     TIMESTAMPTZ,
            last_status     TEXT,
            last_error      TEXT,
            UNIQUE(connector, scope_key)
        );

        CREATE TABLE IF NOT EXISTS kb_audit_log (
            id              BIGSERIAL PRIMARY KEY,
            ts              TIMESTAMPTZ DEFAULT now(),
            actor           TEXT NOT NULL,
            action          TEXT NOT NULL,
            subject_type    TEXT,
            subject_id      TEXT,
            project_id      UUID,
            metadata        JSONB
        );

        CREATE INDEX IF NOT EXISTS idx_audit_actor_ts
            ON kb_audit_log(actor, ts DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_project_ts
            ON kb_audit_log(project_id, ts DESC);

        CREATE TABLE IF NOT EXISTS redaction_vocab (
            id          BIGSERIAL PRIMARY KEY,
            term        TEXT NOT NULL UNIQUE,
            category    TEXT NOT NULL DEFAULT 'client',
            created_at  TIMESTAMPTZ DEFAULT now()
        );
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS redaction_vocab CASCADE;
        DROP INDEX IF EXISTS idx_audit_project_ts;
        DROP INDEX IF EXISTS idx_audit_actor_ts;
        DROP TABLE IF EXISTS kb_audit_log CASCADE;
        DROP TABLE IF EXISTS connector_sync_state CASCADE;
        DROP INDEX IF EXISTS idx_promo_project_status;
        DROP TABLE IF EXISTS promotion_candidates CASCADE;
        DROP TABLE IF EXISTS kb_sources CASCADE;
        DROP INDEX IF EXISTS idx_org_kn_embedding;
        DROP INDEX IF EXISTS idx_org_kn_project;
        DROP TABLE IF EXISTS org_knowledge CASCADE;
        DROP TABLE IF EXISTS org_channel_map CASCADE;
        DROP TABLE IF EXISTS org_project_members CASCADE;
        DROP TABLE IF EXISTS org_projects CASCADE;
    """)
