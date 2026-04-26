"""Backfill author column on org_knowledge.

Revision ID: 011_kb_author
Revises: 010_kb_backfill
Create Date: 2026-04-27

Closes the T8 plan gap noted in 010_kb_backfill: backfill adapters already
populate ``BackfillItem.author`` (Slack user id, Redmine login, Notion
last_edited_by id) but the runner had no column to write it to. The
backfill runner additionally writes a row into ``kb_sources`` per
ingested item using ``BackfillItem.source_uri``, which previously was
deferred — see ``cli.py`` 'kb_sources rows deferred' comment.
"""

from alembic import op

revision = "011_kb_author"
down_revision = "010_kb_backfill"
branch_labels = None
depends_on = None


UPGRADE_SQL = """
ALTER TABLE org_knowledge
    ADD COLUMN IF NOT EXISTS author TEXT;

CREATE INDEX IF NOT EXISTS ix_org_knowledge_author
    ON org_knowledge (project_id, author)
    WHERE author IS NOT NULL AND superseded_by IS NULL;
"""


DOWNGRADE_SQL = """
DROP INDEX IF EXISTS ix_org_knowledge_author;
ALTER TABLE org_knowledge DROP COLUMN IF EXISTS author;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
