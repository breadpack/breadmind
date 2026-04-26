"""messenger: auth (sso, sessions, mfa, passkeys, otp, invites)

Revision ID: 016_messenger_auth
Revises: 015_messenger_files_aux
"""
from alembic import op

revision = "016_messenger_auth"
down_revision = "015_messenger_files_aux"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE sso_configs (
          workspace_id  uuid PRIMARY KEY REFERENCES org_projects(id) ON DELETE CASCADE,
          provider      text NOT NULL CHECK (provider IN ('saml','oidc')),
          config        jsonb NOT NULL,
          enforced      boolean NOT NULL DEFAULT false,
          scim_token_hash bytea,
          updated_at    timestamptz NOT NULL DEFAULT now()
        );
    """)

    op.execute("""
        CREATE TABLE user_sessions (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id         uuid NOT NULL REFERENCES workspace_users(id) ON DELETE CASCADE,
          workspace_id    uuid NOT NULL REFERENCES org_projects(id),
          refresh_token_hash bytea NOT NULL,
          device_info     jsonb,
          ip_address      inet,
          created_at      timestamptz NOT NULL DEFAULT now(),
          expires_at      timestamptz NOT NULL,
          revoked_at      timestamptz,
          last_used_at    timestamptz,
          UNIQUE (refresh_token_hash)
        );
    """)
    op.execute(
        "CREATE INDEX user_sessions_user ON user_sessions (user_id, expires_at) "
        "WHERE revoked_at IS NULL"
    )

    op.execute("""
        CREATE TABLE user_mfa_totp (
          user_id         uuid PRIMARY KEY REFERENCES workspace_users(id) ON DELETE CASCADE,
          secret_encrypted bytea NOT NULL,
          enabled_at      timestamptz NOT NULL DEFAULT now(),
          backup_codes_hashes bytea[] NOT NULL,
          last_used_at    timestamptz
        );
    """)

    op.execute("""
        CREATE TABLE user_passkeys (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id         uuid NOT NULL REFERENCES workspace_users(id) ON DELETE CASCADE,
          credential_id   bytea NOT NULL UNIQUE,
          public_key      bytea NOT NULL,
          counter         bigint NOT NULL DEFAULT 0,
          device_name     text,
          created_at      timestamptz NOT NULL DEFAULT now(),
          last_used_at    timestamptz
        );
    """)

    op.execute("""
        CREATE TABLE email_otp (
          email           citext NOT NULL,
          workspace_slug  text NOT NULL DEFAULT '',
          code_hash       bytea NOT NULL,
          expires_at      timestamptz NOT NULL,
          used_at         timestamptz,
          attempts        integer NOT NULL DEFAULT 0,
          PRIMARY KEY (email, workspace_slug)
        );
    """)

    op.execute("""
        CREATE TABLE workspace_invites (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id    uuid NOT NULL REFERENCES org_projects(id) ON DELETE CASCADE,
          email           citext NOT NULL,
          invited_by      uuid REFERENCES workspace_users(id),
          role            text NOT NULL DEFAULT 'member',
          token_hash      bytea NOT NULL UNIQUE,
          channel_ids     uuid[],
          created_at      timestamptz NOT NULL DEFAULT now(),
          expires_at      timestamptz NOT NULL,
          accepted_at     timestamptz,
          revoked_at      timestamptz
        );
    """)
    op.execute(
        "CREATE INDEX workspace_invites_email ON workspace_invites (email, workspace_id)"
    )


def downgrade() -> None:
    for tbl in (
        "workspace_invites", "email_otp", "user_passkeys",
        "user_mfa_totp", "user_sessions", "sso_configs",
    ):
        op.execute(f"DROP TABLE IF EXISTS {tbl}")
