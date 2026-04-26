"""messenger: files + attachments + custom_emojis + read_cursors + drafts + scheduled + bookmarks

Revision ID: 015_messenger_files_aux
Revises: 014_messenger_messages
"""
from alembic import op

revision = "015_messenger_files_aux"
down_revision = "014_messenger_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # files
    op.execute("""
        CREATE TABLE files (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id    uuid NOT NULL REFERENCES org_projects(id) ON DELETE CASCADE,
          uploader_id     uuid NOT NULL REFERENCES workspace_users(id),
          filename        text NOT NULL,
          mime_type       text NOT NULL,
          size_bytes      bigint NOT NULL,
          storage_backend text NOT NULL DEFAULT 's3'
                          CHECK (storage_backend IN ('s3','fs','minio','gcs','azure_blob')),
          storage_key     text NOT NULL,
          checksum_sha256 bytea,
          thumbnail_key   text,
          uploaded_at     timestamptz NOT NULL DEFAULT now(),
          deleted_at      timestamptz
        );
    """)
    op.execute(
        "CREATE INDEX files_workspace_uploader "
        "ON files (workspace_id, uploader_id, uploaded_at DESC)"
    )

    # message_attachments
    op.execute("""
        CREATE TABLE message_attachments (
          message_id      uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
          file_id         uuid NOT NULL REFERENCES files(id) ON DELETE CASCADE,
          position        integer NOT NULL DEFAULT 0,
          PRIMARY KEY (message_id, file_id)
        );
    """)

    # custom_emojis
    op.execute("""
        CREATE TABLE custom_emojis (
          workspace_id    uuid NOT NULL REFERENCES org_projects(id) ON DELETE CASCADE,
          name            text NOT NULL,
          image_file_id   uuid REFERENCES files(id) ON DELETE SET NULL,
          alias_for       text,
          created_by      uuid REFERENCES workspace_users(id),
          created_at      timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (workspace_id, name),
          CHECK (image_file_id IS NOT NULL OR alias_for IS NOT NULL)
        );
    """)

    # channel_read_cursors
    op.execute("""
        CREATE TABLE channel_read_cursors (
          user_id         uuid NOT NULL REFERENCES workspace_users(id) ON DELETE CASCADE,
          channel_id      uuid NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
          last_read_message_id uuid REFERENCES messages(id),
          last_read_at    timestamptz NOT NULL DEFAULT now(),
          unread_count    integer NOT NULL DEFAULT 0,
          unread_mentions integer NOT NULL DEFAULT 0,
          PRIMARY KEY (user_id, channel_id)
        );
    """)

    # message_drafts
    # thread_key materializes COALESCE so the PK can reference a real column
    # (PG forbids expressions in inline PRIMARY KEY)
    op.execute("""
        CREATE TABLE message_drafts (
          user_id         uuid NOT NULL REFERENCES workspace_users(id) ON DELETE CASCADE,
          channel_id      uuid NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
          thread_parent_id uuid REFERENCES messages(id),
          thread_key      uuid GENERATED ALWAYS AS (
                            COALESCE(thread_parent_id, '00000000-0000-0000-0000-000000000000'::uuid)
                          ) STORED,
          text            text,
          blocks          jsonb,
          updated_at      timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (user_id, channel_id, thread_key)
        );
    """)

    # scheduled_messages
    op.execute("""
        CREATE TABLE scheduled_messages (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id    uuid NOT NULL REFERENCES org_projects(id) ON DELETE CASCADE,
          channel_id      uuid NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
          author_id       uuid NOT NULL REFERENCES workspace_users(id) ON DELETE CASCADE,
          text            text,
          blocks          jsonb,
          scheduled_for   timestamptz NOT NULL,
          created_at      timestamptz NOT NULL DEFAULT now(),
          sent_message_id uuid REFERENCES messages(id),
          cancelled_at    timestamptz
        );
    """)
    op.execute(
        "CREATE INDEX scheduled_messages_due ON scheduled_messages (scheduled_for) "
        "WHERE sent_message_id IS NULL AND cancelled_at IS NULL"
    )

    # bookmarks
    op.execute("""
        CREATE TABLE bookmarks (
          user_id         uuid NOT NULL REFERENCES workspace_users(id) ON DELETE CASCADE,
          message_id      uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
          saved_at        timestamptz NOT NULL DEFAULT now(),
          reminder_at     timestamptz,
          PRIMARY KEY (user_id, message_id)
        );
    """)
    op.execute(
        "CREATE INDEX bookmarks_reminder ON bookmarks (user_id, reminder_at) "
        "WHERE reminder_at IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bookmarks")
    op.execute("DROP TABLE IF EXISTS scheduled_messages")
    op.execute("DROP TABLE IF EXISTS message_drafts")
    op.execute("DROP TABLE IF EXISTS channel_read_cursors")
    op.execute("DROP TABLE IF EXISTS custom_emojis")
    op.execute("DROP TABLE IF EXISTS message_attachments")
    op.execute("DROP TABLE IF EXISTS files CASCADE")
