"""coding_jobs / coding_phases / coding_phase_logs — long-running job monitoring.

Revision ID: 007_coding_jobs
Revises: 006_connector_configs
Create Date: 2026-04-23
"""

from alembic import op

revision = "007_coding_jobs"
down_revision = "006_connector_configs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS coding_jobs (
            id                 TEXT PRIMARY KEY,
            project            TEXT NOT NULL,
            agent              TEXT NOT NULL,
            prompt             TEXT NOT NULL,
            status             TEXT NOT NULL,
            user_name          TEXT NOT NULL DEFAULT '',
            channel            TEXT NOT NULL DEFAULT '',
            started_at         TIMESTAMPTZ NOT NULL,
            finished_at        TIMESTAMPTZ,
            duration_seconds   DOUBLE PRECISION,
            total_phases       INT NOT NULL DEFAULT 0,
            session_id         TEXT NOT NULL DEFAULT '',
            error              TEXT NOT NULL DEFAULT '',
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS idx_coding_jobs_user_started
            ON coding_jobs (user_name, started_at DESC);

        CREATE INDEX IF NOT EXISTS idx_coding_jobs_status_started
            ON coding_jobs (status, started_at DESC);

        CREATE TABLE IF NOT EXISTS coding_phases (
            job_id             TEXT NOT NULL REFERENCES coding_jobs(id) ON DELETE CASCADE,
            step               INT NOT NULL,
            title              TEXT NOT NULL,
            status             TEXT NOT NULL,
            started_at         TIMESTAMPTZ,
            finished_at        TIMESTAMPTZ,
            duration_seconds   DOUBLE PRECISION,
            output_summary     TEXT NOT NULL DEFAULT '',
            files_changed      TEXT[] NOT NULL DEFAULT '{}',
            PRIMARY KEY (job_id, step)
        );

        CREATE TABLE IF NOT EXISTS coding_phase_logs (
            id        BIGSERIAL PRIMARY KEY,
            job_id    TEXT NOT NULL REFERENCES coding_jobs(id) ON DELETE CASCADE,
            step      INT NOT NULL,
            line_no   INT NOT NULL,
            ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
            text      TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_phase_logs_job_step_line
            ON coding_phase_logs (job_id, step, line_no);

        CREATE INDEX IF NOT EXISTS idx_phase_logs_ts_brin
            ON coding_phase_logs USING BRIN (ts);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS idx_phase_logs_ts_brin;
        DROP INDEX IF EXISTS idx_phase_logs_job_step_line;
        DROP TABLE IF EXISTS coding_phase_logs CASCADE;
        DROP TABLE IF EXISTS coding_phases CASCADE;
        DROP INDEX IF EXISTS idx_coding_jobs_status_started;
        DROP INDEX IF EXISTS idx_coding_jobs_user_started;
        DROP TABLE IF EXISTS coding_jobs CASCADE;
    """)
