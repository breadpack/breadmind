"""kb_p3 feedback + rank/flag columns + extraction pause.

Revision ID: 005_kb_p3_feedback
Revises: 004_org_kb
Create Date: 2026-04-21

Phase 3 groundwork for the Slack KB knowledge pipeline:

* ``org_knowledge`` gains ``rank_weight`` (feedback-driven re-ranking
  signal) and ``flag_count`` (downvote / sensitive-flag counter used
  by auto-suppression).
* ``promotion_candidates`` gains ``sensitive_flag`` so the review queue
  can surface candidates flagged by the sensitive classifier.
* New ``kb_feedback`` table stores per-answer user feedback
  (upvote / downvote / bookmark) along with the query/answer context
  for later analysis.
* New ``kb_extraction_pause`` table lets leads pause the extractor
  per-project (consolidated here so Task 11 does not add a second
  revision).
"""

from alembic import op

revision = "005_kb_p3_feedback"
down_revision = "004_org_kb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE org_knowledge
            ADD COLUMN IF NOT EXISTS rank_weight DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            ADD COLUMN IF NOT EXISTS flag_count  INTEGER          NOT NULL DEFAULT 0;

        ALTER TABLE promotion_candidates
            ADD COLUMN IF NOT EXISTS sensitive_flag BOOLEAN NOT NULL DEFAULT FALSE;

        CREATE TABLE IF NOT EXISTS kb_feedback (
            id              BIGSERIAL PRIMARY KEY,
            knowledge_id    BIGINT REFERENCES org_knowledge(id) ON DELETE CASCADE,
            user_id         TEXT NOT NULL,
            kind            TEXT NOT NULL,
            query_text      TEXT,
            answer_text     TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS idx_kb_feedback_knowledge
            ON kb_feedback(knowledge_id, kind);
        CREATE INDEX IF NOT EXISTS idx_kb_feedback_user_ts
            ON kb_feedback(user_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS kb_extraction_pause (
            project_id  UUID PRIMARY KEY,
            paused      BOOLEAN NOT NULL DEFAULT FALSE,
            reason      TEXT,
            paused_at   TIMESTAMPTZ
        );
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS kb_extraction_pause CASCADE;
        DROP INDEX IF EXISTS idx_kb_feedback_user_ts;
        DROP INDEX IF EXISTS idx_kb_feedback_knowledge;
        DROP TABLE IF EXISTS kb_feedback CASCADE;
        ALTER TABLE promotion_candidates
            DROP COLUMN IF EXISTS sensitive_flag;
        ALTER TABLE org_knowledge
            DROP COLUMN IF EXISTS flag_count,
            DROP COLUMN IF EXISTS rank_weight;
    """)
