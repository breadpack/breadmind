"""outbox_notify_trigger

Revision ID: 021_outbox_notify_trigger
Revises: 020_messenger_m1_cleanup
Create Date: 2026-04-29

Adds AFTER INSERT trigger on ``message_outbox`` that calls
``pg_notify('outbox_new', NEW.id::text)``. NOTIFY is delivered after the
transaction commits, so dispatcher LISTEN'ers receive only committed rows.

Pairs with ``OutboxDispatcher`` (FU-1): the dispatcher LISTENs on the
``outbox_new`` channel for sub-second wakeups while a 5s safety polling
loop guarantees forward progress if a NOTIFY is missed (e.g., during the
brief window before LISTEN registers, or across reconnects).
"""
from __future__ import annotations
from alembic import op


# revision identifiers, used by Alembic.
revision = "021_outbox_notify_trigger"
down_revision = "020_messenger_m1_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION messenger_outbox_notify() RETURNS trigger AS $$
        BEGIN
            PERFORM pg_notify('outbox_new', NEW.id::text);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER message_outbox_notify_trigger
        AFTER INSERT ON message_outbox
        FOR EACH ROW
        EXECUTE FUNCTION messenger_outbox_notify();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS message_outbox_notify_trigger ON message_outbox;")
    op.execute("DROP FUNCTION IF EXISTS messenger_outbox_notify();")
