"""messenger: workspace_users + org_projects extension

Revision ID: 012_messenger_workspace_users
Revises: 011_kb_author
Create Date: 2026-04-26

Changes:
- org_projects.slack_team_id is made NULLable (Option A) because native
  messenger workspaces are not Slack-backed and the column is meaningless
  for them.  Existing Slack-backed rows retain their value; only the NOT
  NULL constraint is relaxed.
- New columns added to org_projects: name (already existed, kept as-is),
  slug, domain, icon_url, plan, created_by, archived_at, default_channel_id.
- New tables: workspace_users, user_groups, user_group_members.

Note: This migration requires the database role to have permission to install
the ``citext`` extension. On managed Postgres services (RDS, Cloud SQL, AlloyDB)
this typically requires ``rds_superuser`` or equivalent. The deployment baseline
(``pgvector/pgvector:pg17`` Docker image) grants this by default.
"""
from alembic import op

revision = "012_messenger_workspace_users"
down_revision = "011_kb_author"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    # Relax the NOT NULL constraint on slack_team_id so native (non-Slack)
    # workspaces can be inserted without a dummy value (Option A).
    op.execute("""
        ALTER TABLE org_projects
          ALTER COLUMN slack_team_id DROP NOT NULL;
    """)

    # Extend org_projects with messenger workspace columns.
    # 'name' already exists as NOT NULL TEXT — skip it.
    op.execute("""
        ALTER TABLE org_projects
          ADD COLUMN IF NOT EXISTS slug              text UNIQUE,
          ADD COLUMN IF NOT EXISTS domain            text,
          ADD COLUMN IF NOT EXISTS icon_url          text,
          ADD COLUMN IF NOT EXISTS plan              text NOT NULL DEFAULT 'free'
            CHECK (plan IN ('free','pro','business','enterprise')),
          ADD COLUMN IF NOT EXISTS created_by        uuid,
          ADD COLUMN IF NOT EXISTS archived_at       timestamptz,
          ADD COLUMN IF NOT EXISTS default_channel_id uuid;
    """)

    op.execute("""
        CREATE TABLE workspace_users (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id    uuid NOT NULL REFERENCES org_projects(id) ON DELETE CASCADE,
          external_id     text,
          email           citext NOT NULL,
          kind            text NOT NULL CHECK (kind IN ('human','bot','agent')),
          display_name    text NOT NULL,
          real_name       text,
          avatar_url      text,
          status_text     text,
          status_emoji    text,
          status_expires_at timestamptz,
          timezone        text,
          locale          text DEFAULT 'ko',
          custom_fields   jsonb DEFAULT '{}'::jsonb,
          role            text NOT NULL DEFAULT 'member'
                          CHECK (role IN ('owner','admin','member','guest','single_channel_guest')),
          invited_by      uuid REFERENCES workspace_users(id),
          joined_at       timestamptz NOT NULL DEFAULT now(),
          deactivated_at  timestamptz,
          legacy_slack_id text,
          agent_config    jsonb,
          bot_app_id      uuid,
          UNIQUE (workspace_id, email),
          UNIQUE (workspace_id, external_id) DEFERRABLE INITIALLY DEFERRED
        );
    """)
    op.execute("CREATE INDEX workspace_users_kind ON workspace_users (workspace_id, kind)")
    op.execute(
        "CREATE INDEX workspace_users_active ON workspace_users (workspace_id) "
        "WHERE deactivated_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX workspace_users_legacy_slack "
        "ON workspace_users (workspace_id, legacy_slack_id) WHERE legacy_slack_id IS NOT NULL"
    )

    # Forward FK on org_projects.created_by — added after workspace_users exists.
    op.execute("""
        ALTER TABLE org_projects
          ADD CONSTRAINT org_projects_created_by_fk
          FOREIGN KEY (created_by) REFERENCES workspace_users(id) ON DELETE SET NULL;
    """)

    op.execute("""
        CREATE TABLE user_groups (
          id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id  uuid NOT NULL REFERENCES org_projects(id) ON DELETE CASCADE,
          handle        text NOT NULL,
          name          text NOT NULL,
          description   text,
          created_by    uuid REFERENCES workspace_users(id),
          created_at    timestamptz NOT NULL DEFAULT now(),
          UNIQUE (workspace_id, handle)
        );
    """)
    op.execute("""
        CREATE TABLE user_group_members (
          group_id      uuid NOT NULL REFERENCES user_groups(id) ON DELETE CASCADE,
          user_id       uuid NOT NULL REFERENCES workspace_users(id) ON DELETE CASCADE,
          PRIMARY KEY (group_id, user_id)
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_group_members")
    op.execute("DROP TABLE IF EXISTS user_groups")
    op.execute("ALTER TABLE org_projects DROP CONSTRAINT IF EXISTS org_projects_created_by_fk")
    op.execute("DROP TABLE IF EXISTS workspace_users CASCADE")
    op.execute("""
        ALTER TABLE org_projects
          DROP COLUMN IF EXISTS default_channel_id,
          DROP COLUMN IF EXISTS archived_at,
          DROP COLUMN IF EXISTS created_by,
          DROP COLUMN IF EXISTS plan,
          DROP COLUMN IF EXISTS icon_url,
          DROP COLUMN IF EXISTS domain,
          DROP COLUMN IF EXISTS slug;
    """)
    # Restore the NOT NULL constraint on slack_team_id.
    # Fail loudly if any messenger-native workspaces (slack_team_id IS NULL)
    # still exist — silently backfilling synthetic values would corrupt those
    # rows and make them undetectable as native workspaces on re-upgrade.
    # The operator must resolve them (delete or supply a real Slack team_id)
    # before retrying the downgrade.
    op.execute("""
        DO $$
        DECLARE
            null_count integer;
        BEGIN
            SELECT count(*) INTO null_count FROM org_projects WHERE slack_team_id IS NULL;
            IF null_count > 0 THEN
                RAISE EXCEPTION
                  'Cannot downgrade migration 012: % org_projects rows have NULL slack_team_id '
                  '(messenger-native workspaces). Resolve by deleting these workspaces '
                  '(DELETE FROM org_projects WHERE slack_team_id IS NULL) or backfilling '
                  'a real Slack team_id, then retry the downgrade.', null_count;
            END IF;
        END
        $$;
    """)
    op.execute("ALTER TABLE org_projects ALTER COLUMN slack_team_id SET NOT NULL;")
    op.execute("DROP EXTENSION IF EXISTS citext")
