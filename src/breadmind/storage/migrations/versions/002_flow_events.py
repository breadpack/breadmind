"""Flow events tables: durable task flow system.

Revision ID: 002_flow_events
Revises: 001_baseline
Create Date: 2026-04-10

Introduces the append-only event log and projection tables that
back the Durable Task Flow + SDUI feature (Phase 1).

Tables
------
flow_events
    Append-only event log keyed by (flow_id, seq). The source of
    truth for all flow state transitions.
flows
    Projection of the current state of a flow (title, status,
    last_event_seq, summary) for fast list/detail queries.
flow_steps
    Per-step projection with tool/args/status/result, used by
    executors and the SDUI renderer.
"""

from alembic import op

revision = "002_flow_events"
down_revision = "001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        -- Append-only event log (source of truth)
        CREATE TABLE IF NOT EXISTS flow_events (
            id BIGSERIAL PRIMARY KEY,
            flow_id UUID NOT NULL,
            seq BIGINT NOT NULL,
            event_type TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            actor TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            schema_version SMALLINT NOT NULL DEFAULT 1,
            UNIQUE (flow_id, seq)
        );

        CREATE INDEX IF NOT EXISTS idx_flow_events_flow
            ON flow_events (flow_id, seq);
        CREATE INDEX IF NOT EXISTS idx_flow_events_type_time
            ON flow_events (event_type, created_at);

        -- Flow projection (current state)
        CREATE TABLE IF NOT EXISTS flows (
            id UUID PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            user_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            origin TEXT DEFAULT 'chat',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_event_seq BIGINT NOT NULL DEFAULT 0,
            summary JSONB,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        );

        CREATE INDEX IF NOT EXISTS idx_flows_user_status
            ON flows (user_id, status, updated_at DESC);

        -- Flow step projection
        CREATE TABLE IF NOT EXISTS flow_steps (
            flow_id UUID NOT NULL REFERENCES flows(id) ON DELETE CASCADE,
            step_id TEXT NOT NULL,
            title TEXT NOT NULL,
            tool TEXT,
            args JSONB NOT NULL DEFAULT '{}'::jsonb,
            depends_on TEXT[] NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            attempt INT NOT NULL DEFAULT 0,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            result JSONB,
            error TEXT,
            PRIMARY KEY (flow_id, step_id)
        );

        CREATE INDEX IF NOT EXISTS idx_flow_steps_status
            ON flow_steps (flow_id, status);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS flow_steps CASCADE;
        DROP TABLE IF EXISTS flows CASCADE;
        DROP TABLE IF EXISTS flow_events CASCADE;
    """)
