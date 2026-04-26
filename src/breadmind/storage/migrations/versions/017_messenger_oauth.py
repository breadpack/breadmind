"""messenger: oauth_apps + oauth_tokens + workspace_users.bot_app_id FK

Revision ID: 017_messenger_oauth
Revises: 016_messenger_auth
"""
from alembic import op

revision = "017_messenger_oauth"
down_revision = "016_messenger_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE oauth_apps (
          id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id        uuid NOT NULL REFERENCES org_projects(id) ON DELETE CASCADE,
          name                text NOT NULL,
          description         text,
          client_id           text NOT NULL UNIQUE,
          client_secret_hash  bytea NOT NULL,
          redirect_uris       text[] NOT NULL,
          scopes              text[] NOT NULL,
          events_url          text,
          interactivity_url   text,
          command_url         text,
          signing_secret_hash bytea,
          created_by          uuid REFERENCES workspace_users(id),
          created_at          timestamptz NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        ALTER TABLE workspace_users
          ADD CONSTRAINT workspace_users_bot_app_fk
          FOREIGN KEY (bot_app_id) REFERENCES oauth_apps(id) ON DELETE SET NULL;
    """)

    op.execute("""
        CREATE TABLE oauth_tokens (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          app_id          uuid NOT NULL REFERENCES oauth_apps(id) ON DELETE CASCADE,
          workspace_id    uuid NOT NULL REFERENCES org_projects(id),
          user_id         uuid REFERENCES workspace_users(id),
          token_kind      text NOT NULL CHECK (token_kind IN ('bot','user','app_level','refresh')),
          token_hash      bytea NOT NULL,
          scopes          text[] NOT NULL,
          bot_user_id     uuid REFERENCES workspace_users(id),
          expires_at      timestamptz,
          created_at      timestamptz NOT NULL DEFAULT now(),
          revoked_at      timestamptz,
          UNIQUE (token_hash)
        );
    """)
    op.execute(
        "CREATE INDEX oauth_tokens_lookup ON oauth_tokens (token_hash) WHERE revoked_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS oauth_tokens")
    op.execute("ALTER TABLE workspace_users DROP CONSTRAINT IF EXISTS workspace_users_bot_app_fk")
    op.execute("DROP TABLE IF EXISTS oauth_apps")
