"""episodic memory — org_id UUID FK to org_projects + composite indexes.

Revision ID: 009_episodic_org_id
Revises: 008_episodic_recorder
Create Date: 2026-04-26
"""

from alembic import op

revision = "009_episodic_org_id"
down_revision = "008_episodic_recorder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE episodic_notes
            ADD COLUMN IF NOT EXISTS org_id UUID
            REFERENCES org_projects(id) ON DELETE SET NULL;

        CREATE INDEX IF NOT EXISTS ix_episodic_org_user_kind_recent
            ON episodic_notes (org_id, user_id, kind, created_at DESC);

        CREATE INDEX IF NOT EXISTS ix_episodic_org_tool_outcome
            ON episodic_notes (org_id, tool_name, outcome, created_at DESC)
            WHERE tool_name IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS ix_episodic_org_tool_outcome;
        DROP INDEX IF EXISTS ix_episodic_org_user_kind_recent;
        ALTER TABLE episodic_notes DROP COLUMN IF EXISTS org_id;
    """)
