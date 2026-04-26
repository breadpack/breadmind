"""messenger M1 cleanup: notification_pref NOT NULL, episodic_link integer, message_mentions PK 분리

Revision ID: 020_messenger_m1_cleanup
Revises: 019_messenger_scheduled

후속 cleanup 3건 일괄 처리:
1. channel_members.notification_pref NOT NULL (013에서 누락)
2. messages.episodic_link / agent_actions.episodic_note_id bigint → integer
   (episodic_notes.id는 SERIAL=int4이므로 정확매칭)
3. message_mentions PK에서 target_id 제외 + 부분 unique index 분리
   (here/everyone broadcast는 target_id NULL이라 기존 PK로 INSERT 불가)
"""
from alembic import op

revision = "020_messenger_m1_cleanup"
down_revision = "019_messenger_scheduled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. channel_members.notification_pref NOT NULL
    op.execute(
        "UPDATE channel_members SET notification_pref = 'all' "
        "WHERE notification_pref IS NULL"
    )
    op.execute(
        "ALTER TABLE channel_members "
        "ALTER COLUMN notification_pref SET NOT NULL"
    )

    # 2a. messages.episodic_link bigint → integer
    op.execute("ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_episodic_link_fkey")
    op.execute("DROP INDEX IF EXISTS messages_episodic")
    op.execute(
        "ALTER TABLE messages "
        "ALTER COLUMN episodic_link TYPE integer USING episodic_link::integer"
    )
    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT messages_episodic_link_fkey "
        "FOREIGN KEY (episodic_link) REFERENCES episodic_notes(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX messages_episodic ON messages (episodic_link) "
        "WHERE episodic_link IS NOT NULL"
    )

    # 2b. agent_actions.episodic_note_id bigint → integer
    op.execute(
        "ALTER TABLE agent_actions "
        "DROP CONSTRAINT IF EXISTS agent_actions_episodic_note_id_fkey"
    )
    op.execute(
        "ALTER TABLE agent_actions "
        "ALTER COLUMN episodic_note_id TYPE integer USING episodic_note_id::integer"
    )
    op.execute(
        "ALTER TABLE agent_actions ADD CONSTRAINT agent_actions_episodic_note_id_fkey "
        "FOREIGN KEY (episodic_note_id) REFERENCES episodic_notes(id) ON DELETE SET NULL"
    )

    # 3. message_mentions PK 분리
    #    PK가 컬럼에 강제하던 NOT NULL을 명시적으로 해제해야 broadcast(target_id NULL)
    #    INSERT가 가능해진다 (PostgreSQL은 DROP CONSTRAINT만으로는 NOT NULL을 풀지 않는다).
    op.execute("ALTER TABLE message_mentions DROP CONSTRAINT message_mentions_pkey")
    op.execute(
        "ALTER TABLE message_mentions "
        "ALTER COLUMN target_id DROP NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX message_mentions_targeted "
        "ON message_mentions (message_id, mention_kind, target_id) "
        "WHERE target_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX message_mentions_broadcast "
        "ON message_mentions (message_id, mention_kind) "
        "WHERE target_id IS NULL"
    )


def downgrade() -> None:
    # 3. message_mentions PK 복원 (broadcast 행은 PK 위배라 삭제 후 복원)
    op.execute("DROP INDEX IF EXISTS message_mentions_targeted")
    op.execute("DROP INDEX IF EXISTS message_mentions_broadcast")
    op.execute("DELETE FROM message_mentions WHERE target_id IS NULL")
    op.execute(
        "ALTER TABLE message_mentions ADD CONSTRAINT message_mentions_pkey "
        "PRIMARY KEY (message_id, mention_kind, target_id)"
    )

    # 2b. agent_actions.episodic_note_id integer → bigint
    op.execute(
        "ALTER TABLE agent_actions "
        "DROP CONSTRAINT IF EXISTS agent_actions_episodic_note_id_fkey"
    )
    op.execute(
        "ALTER TABLE agent_actions "
        "ALTER COLUMN episodic_note_id TYPE bigint USING episodic_note_id::bigint"
    )
    op.execute(
        "ALTER TABLE agent_actions ADD CONSTRAINT agent_actions_episodic_note_id_fkey "
        "FOREIGN KEY (episodic_note_id) REFERENCES episodic_notes(id) ON DELETE SET NULL"
    )

    # 2a. messages.episodic_link integer → bigint
    op.execute("ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_episodic_link_fkey")
    op.execute("DROP INDEX IF EXISTS messages_episodic")
    op.execute(
        "ALTER TABLE messages "
        "ALTER COLUMN episodic_link TYPE bigint USING episodic_link::bigint"
    )
    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT messages_episodic_link_fkey "
        "FOREIGN KEY (episodic_link) REFERENCES episodic_notes(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX messages_episodic ON messages (episodic_link) "
        "WHERE episodic_link IS NOT NULL"
    )

    # 1. channel_members.notification_pref NOT NULL 해제
    op.execute(
        "ALTER TABLE channel_members "
        "ALTER COLUMN notification_pref DROP NOT NULL"
    )
