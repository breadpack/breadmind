"""messenger: messages + edits + reactions + pins + mentions + outbox

Revision ID: 014_messenger_messages
Revises: 013_messenger_channels
"""
from alembic import op

revision = "014_messenger_messages"
down_revision = "013_messenger_channels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("""
        CREATE TABLE messages (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id    uuid NOT NULL REFERENCES org_projects(id) ON DELETE CASCADE,
          channel_id      uuid NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
          author_id       uuid NOT NULL REFERENCES workspace_users(id),
          parent_id       uuid REFERENCES messages(id) ON DELETE CASCADE,
          kind            text NOT NULL DEFAULT 'text'
                          CHECK (kind IN ('text','agent_action','episodic_recall',
                                          'tool_call','approval_request','system')),
          text            text,
          blocks          jsonb DEFAULT '[]'::jsonb,
          agent_payload   jsonb,
          episodic_link   bigint REFERENCES episodic_notes(id) ON DELETE SET NULL,
          tool_call_id    uuid,
          created_at      timestamptz NOT NULL DEFAULT now(),
          edited_at       timestamptz,
          deleted_at      timestamptz,
          client_msg_id   uuid,
          ts_seq          bigint NOT NULL,
          legacy_slack_ts text,
          text_tsvector   tsvector GENERATED ALWAYS AS (
                            to_tsvector('simple', coalesce(text, ''))
                          ) STORED,
          embedding       vector(1024),
          UNIQUE (channel_id, ts_seq)
        );
    """)
    op.execute(
        "CREATE UNIQUE INDEX messages_client_msg_id "
        "ON messages (workspace_id, client_msg_id) WHERE client_msg_id IS NOT NULL"
    )
    op.execute("CREATE INDEX messages_channel_created ON messages (channel_id, created_at DESC)")
    op.execute("CREATE INDEX messages_thread ON messages (parent_id) WHERE parent_id IS NOT NULL")
    op.execute("CREATE INDEX messages_episodic ON messages (episodic_link) WHERE episodic_link IS NOT NULL")
    op.execute("CREATE INDEX messages_kind ON messages (workspace_id, kind) WHERE kind != 'text'")
    op.execute("CREATE INDEX messages_text_fts ON messages USING GIN (text_tsvector)")
    op.execute(
        "CREATE INDEX messages_embedding ON messages USING hnsw "
        "(embedding vector_cosine_ops) WHERE embedding IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX messages_legacy_slack ON messages (workspace_id, legacy_slack_ts) "
        "WHERE legacy_slack_ts IS NOT NULL"
    )

    op.execute("""
        CREATE TABLE message_edits (
          message_id      uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
          edited_at       timestamptz NOT NULL,
          prev_text       text,
          prev_blocks     jsonb,
          edited_by       uuid REFERENCES workspace_users(id),
          PRIMARY KEY (message_id, edited_at)
        );
    """)

    op.execute("""
        CREATE TABLE message_reactions (
          message_id      uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
          user_id         uuid NOT NULL REFERENCES workspace_users(id) ON DELETE CASCADE,
          emoji           text NOT NULL,
          reacted_at      timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (message_id, user_id, emoji)
        );
    """)
    op.execute("CREATE INDEX message_reactions_emoji ON message_reactions (message_id, emoji)")

    op.execute("""
        CREATE TABLE message_pins (
          channel_id      uuid NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
          message_id      uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
          pinned_by       uuid NOT NULL REFERENCES workspace_users(id),
          pinned_at       timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (channel_id, message_id)
        );
    """)

    op.execute("""
        CREATE TABLE message_mentions (
          message_id      uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
          mention_kind    text NOT NULL
                          CHECK (mention_kind IN ('user','channel','here','everyone','group')),
          target_id       uuid,
          PRIMARY KEY (message_id, mention_kind, target_id)
        );
    """)
    op.execute("CREATE INDEX message_mentions_target ON message_mentions (target_id, mention_kind)")

    op.execute("""
        CREATE TABLE message_outbox (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id    uuid NOT NULL,
          channel_id      uuid NOT NULL,
          event_type      text NOT NULL,
          payload         jsonb NOT NULL,
          expires_at      timestamptz NOT NULL,
          created_at      timestamptz NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX message_outbox_expires ON message_outbox (expires_at)")
    op.execute("CREATE INDEX message_outbox_channel ON message_outbox (channel_id, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS message_outbox")
    op.execute("DROP TABLE IF EXISTS message_mentions")
    op.execute("DROP TABLE IF EXISTS message_pins")
    op.execute("DROP TABLE IF EXISTS message_reactions")
    op.execute("DROP TABLE IF EXISTS message_edits")
    op.execute("DROP TABLE IF EXISTS messages CASCADE")
