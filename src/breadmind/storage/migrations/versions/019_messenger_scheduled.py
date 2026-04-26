"""messenger: scheduled_messages table

Revision ID: 019_messenger_scheduled
Revises: 018_messenger_agent_skeleton
"""
from alembic import op

revision = "019_messenger_scheduled"
down_revision = "018_messenger_agent_skeleton"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_messages (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id    uuid NOT NULL REFERENCES org_projects(id) ON DELETE CASCADE,
          channel_id      uuid NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
          author_id       uuid NOT NULL REFERENCES workspace_users(id) ON DELETE CASCADE,
          text            text,
          blocks          jsonb DEFAULT '[]'::jsonb,
          scheduled_for   timestamptz NOT NULL,
          created_at      timestamptz NOT NULL DEFAULT now(),
          sent_message_id uuid REFERENCES messages(id) ON DELETE SET NULL,
          cancelled_at    timestamptz
        );
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS scheduled_messages_due "
        "ON scheduled_messages (scheduled_for) "
        "WHERE sent_message_id IS NULL AND cancelled_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS scheduled_messages_author "
        "ON scheduled_messages (workspace_id, author_id, scheduled_for)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS scheduled_messages")
