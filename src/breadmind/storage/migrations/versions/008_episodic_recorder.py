"""episodic memory recorder — kind/outcome/session/user/summary/pinned + indexes.

Revision ID: 008_episodic_recorder
Revises: 007_coding_jobs
Create Date: 2026-04-25
"""

from alembic import op

revision = "008_episodic_recorder"
down_revision = "007_coding_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE episodic_notes
            ADD COLUMN IF NOT EXISTS kind             VARCHAR(32)  NOT NULL DEFAULT 'neutral',
            ADD COLUMN IF NOT EXISTS tool_name        VARCHAR(128),
            ADD COLUMN IF NOT EXISTS tool_args_digest VARCHAR(16),
            ADD COLUMN IF NOT EXISTS outcome          VARCHAR(16)  NOT NULL DEFAULT 'neutral',
            ADD COLUMN IF NOT EXISTS session_id       UUID,
            ADD COLUMN IF NOT EXISTS user_id          VARCHAR(128),
            ADD COLUMN IF NOT EXISTS summary          TEXT         NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS pinned           BOOLEAN      NOT NULL DEFAULT FALSE;

        CREATE INDEX IF NOT EXISTS ix_episodic_user_kind_recent
            ON episodic_notes (user_id, kind, created_at DESC);

        CREATE INDEX IF NOT EXISTS ix_episodic_user_tool_outcome
            ON episodic_notes (user_id, tool_name, outcome, created_at DESC)
            WHERE tool_name IS NOT NULL;

        CREATE INDEX IF NOT EXISTS ix_episodic_keywords_gin
            ON episodic_notes USING GIN (keywords);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS ix_episodic_keywords_gin;
        DROP INDEX IF EXISTS ix_episodic_user_tool_outcome;
        DROP INDEX IF EXISTS ix_episodic_user_kind_recent;

        ALTER TABLE episodic_notes
            DROP COLUMN IF EXISTS pinned,
            DROP COLUMN IF EXISTS summary,
            DROP COLUMN IF EXISTS user_id,
            DROP COLUMN IF EXISTS session_id,
            DROP COLUMN IF EXISTS outcome,
            DROP COLUMN IF EXISTS tool_args_digest,
            DROP COLUMN IF EXISTS tool_name,
            DROP COLUMN IF EXISTS kind;
    """)
