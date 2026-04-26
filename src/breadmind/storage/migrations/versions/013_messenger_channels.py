"""messenger: channels + members + dm_keys

Revision ID: 013_messenger_channels
Revises: 012_messenger_workspace_users
"""
from alembic import op

revision = "013_messenger_channels"
down_revision = "012_messenger_workspace_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE channels (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id    uuid NOT NULL REFERENCES org_projects(id) ON DELETE CASCADE,
          kind            text NOT NULL CHECK (kind IN ('public','private','dm','mpdm')),
          name            text,
          topic           text,
          purpose         text,
          is_general      boolean NOT NULL DEFAULT false,
          is_archived     boolean NOT NULL DEFAULT false,
          created_by      uuid REFERENCES workspace_users(id),
          created_at      timestamptz NOT NULL DEFAULT now(),
          archived_at     timestamptz,
          last_message_at timestamptz,
          posting_policy  text NOT NULL DEFAULT 'all'
                          CHECK (posting_policy IN ('all','admins','specific_roles')),
          legacy_slack_id text,
          CHECK (
            (kind IN ('public','private') AND name IS NOT NULL) OR
            (kind IN ('dm','mpdm') AND name IS NULL)
          )
        );
    """)
    op.execute(
        "CREATE UNIQUE INDEX channels_name_unique "
        "ON channels (workspace_id, name) WHERE kind IN ('public','private')"
    )
    op.execute("CREATE INDEX channels_workspace_kind ON channels (workspace_id, kind, is_archived)")
    op.execute(
        "CREATE UNIQUE INDEX channels_legacy_slack "
        "ON channels (workspace_id, legacy_slack_id) WHERE legacy_slack_id IS NOT NULL"
    )

    # forward FK from org_projects.default_channel_id
    op.execute("""
        ALTER TABLE org_projects
          ADD CONSTRAINT org_projects_default_channel_fk
          FOREIGN KEY (default_channel_id) REFERENCES channels(id) ON DELETE SET NULL;
    """)

    op.execute("""
        CREATE TABLE channel_members (
          channel_id        uuid NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
          user_id           uuid NOT NULL REFERENCES workspace_users(id) ON DELETE CASCADE,
          role              text NOT NULL DEFAULT 'member'
                            CHECK (role IN ('member','admin')),
          joined_at         timestamptz NOT NULL DEFAULT now(),
          notification_pref text DEFAULT 'all'
                            CHECK (notification_pref IN ('all','mentions','none')),
          muted             boolean NOT NULL DEFAULT false,
          PRIMARY KEY (channel_id, user_id)
        );
    """)
    op.execute("CREATE INDEX channel_members_user ON channel_members (user_id)")

    op.execute("""
        CREATE TABLE dm_keys (
          workspace_id    uuid NOT NULL REFERENCES org_projects(id) ON DELETE CASCADE,
          members_hash    bytea NOT NULL,
          channel_id      uuid NOT NULL UNIQUE REFERENCES channels(id) ON DELETE CASCADE,
          PRIMARY KEY (workspace_id, members_hash)
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dm_keys")
    op.execute("DROP TABLE IF EXISTS channel_members")
    op.execute("ALTER TABLE org_projects DROP CONSTRAINT IF EXISTS org_projects_default_channel_fk")
    op.execute("DROP TABLE IF EXISTS channels CASCADE")
