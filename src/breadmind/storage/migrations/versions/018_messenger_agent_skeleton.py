"""messenger: agent_actions + subscriptions + episodic_notes ALTER + audit_log ALTER

Revision ID: 018_messenger_agent_skeleton
Revises: 017_messenger_oauth
"""
from alembic import op

revision = "018_messenger_agent_skeleton"
down_revision = "017_messenger_oauth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE agent_actions (
          id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id      uuid NOT NULL REFERENCES org_projects(id) ON DELETE CASCADE,
          message_id        uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
          agent_user_id     uuid NOT NULL REFERENCES workspace_users(id),
          action_kind       text NOT NULL CHECK (action_kind IN (
                              'tool_call','recall','approval_request','plan_step','reflection')),
          tool_name         text,
          tool_args         jsonb,
          tool_result       jsonb,
          approval_status   text CHECK (approval_status IN ('pending','approved','rejected')),
          approved_by       uuid REFERENCES workspace_users(id),
          approved_at       timestamptz,
          episodic_note_id  bigint REFERENCES episodic_notes(id) ON DELETE SET NULL,
          created_at        timestamptz NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX agent_actions_message ON agent_actions (message_id)")
    op.execute(
        "CREATE INDEX agent_actions_pending ON agent_actions (workspace_id, approval_status) "
        "WHERE approval_status = 'pending'"
    )
    op.execute(
        "CREATE INDEX agent_actions_agent_user "
        "ON agent_actions (agent_user_id, created_at DESC)"
    )

    op.execute("""
        CREATE TABLE agent_channel_subscriptions (
          channel_id        uuid NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
          agent_user_id     uuid NOT NULL REFERENCES workspace_users(id) ON DELETE CASCADE,
          trigger_mode      text NOT NULL DEFAULT 'mention'
                            CHECK (trigger_mode IN ('mention','always','lurk_only','never')),
          capture_episodic  boolean NOT NULL DEFAULT true,
          enabled_at        timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (channel_id, agent_user_id)
        );
    """)

    # episodic_notes ALTER — bigint matches episodic_notes.id which is SERIAL (integer/bigint)
    op.execute("""
        ALTER TABLE episodic_notes
          ADD COLUMN IF NOT EXISTS source_message_id uuid REFERENCES messages(id) ON DELETE SET NULL,
          ADD COLUMN IF NOT EXISTS source_channel_id uuid REFERENCES channels(id) ON DELETE SET NULL;
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS episodic_notes_source_msg "
        "ON episodic_notes (source_message_id) WHERE source_message_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS episodic_notes_source_channel "
        "ON episodic_notes (source_channel_id, created_at DESC) WHERE source_channel_id IS NOT NULL"
    )

    op.execute("""
        ALTER TABLE audit_log
          ADD COLUMN IF NOT EXISTS actor_user_id  uuid,
          ADD COLUMN IF NOT EXISTS workspace_id   uuid,
          ADD COLUMN IF NOT EXISTS entity_kind    text,
          ADD COLUMN IF NOT EXISTS entity_id      uuid,
          ADD COLUMN IF NOT EXISTS action         text,
          ADD COLUMN IF NOT EXISTS payload        jsonb,
          ADD COLUMN IF NOT EXISTS ip_address     inet,
          ADD COLUMN IF NOT EXISTS user_agent     text,
          ADD COLUMN IF NOT EXISTS occurred_at    timestamptz DEFAULT now();
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS audit_log_workspace_occurred "
        "ON audit_log (workspace_id, occurred_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS audit_log_entity ON audit_log (entity_kind, entity_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_channel_subscriptions")
    op.execute("DROP TABLE IF EXISTS agent_actions")
    op.execute("ALTER TABLE episodic_notes "
               "DROP COLUMN IF EXISTS source_message_id, "
               "DROP COLUMN IF EXISTS source_channel_id")
    # audit_log columns 보존 (drop 시 운영 데이터 손실 가능)
