"""Baseline migration: create all existing tables.

Revision ID: 001_baseline
Revises: None
Create Date: 2026-04-05

This migration captures the full schema that was previously created
inline by database.py _migrate() and the v2 memory plugin tables.
All statements use IF NOT EXISTS for compatibility with databases
that already have these tables.
"""

from alembic import op

revision = "001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE EXTENSION IF NOT EXISTS pgcrypto;

        -- audit_log
        CREATE TABLE IF NOT EXISTS audit_log (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMPTZ DEFAULT NOW(),
            action TEXT NOT NULL,
            params JSONB DEFAULT '{}',
            result TEXT NOT NULL,
            reason TEXT DEFAULT '',
            channel TEXT DEFAULT '',
            "user" TEXT DEFAULT ''
        );

        -- episodic_notes
        CREATE TABLE IF NOT EXISTS episodic_notes (
            id SERIAL PRIMARY KEY,
            content TEXT NOT NULL,
            keywords TEXT[] DEFAULT '{}',
            tags TEXT[] DEFAULT '{}',
            context_description TEXT DEFAULT '',
            embedding FLOAT8[],
            linked_note_ids INTEGER[] DEFAULT '{}',
            decay_weight FLOAT8 DEFAULT 1.0,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- kg_entities
        CREATE TABLE IF NOT EXISTS kg_entities (
            id TEXT PRIMARY KEY,
            entity_type TEXT,
            name TEXT,
            properties JSONB DEFAULT '{}',
            weight FLOAT8 DEFAULT 1.0,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- kg_relations
        CREATE TABLE IF NOT EXISTS kg_relations (
            id SERIAL PRIMARY KEY,
            source TEXT REFERENCES kg_entities(id),
            target TEXT REFERENCES kg_entities(id),
            relation_type TEXT,
            weight FLOAT8 DEFAULT 1.0,
            properties JSONB DEFAULT '{}'
        );

        -- settings
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value JSONB NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- mcp_servers
        CREATE TABLE IF NOT EXISTS mcp_servers (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            install_config JSONB NOT NULL,
            status TEXT DEFAULT 'stopped',
            installed_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- conversations
        CREATE TABLE IF NOT EXISTS conversations (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT '',
            channel TEXT NOT NULL DEFAULT '',
            title TEXT DEFAULT '',
            messages JSONB NOT NULL DEFAULT '[]',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            last_active TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_conversations_user
            ON conversations(user_id);
        CREATE INDEX IF NOT EXISTS idx_conversations_active
            ON conversations(last_active DESC);

        -- tasks
        CREATE TABLE IF NOT EXISTS tasks (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            title TEXT NOT NULL,
            description TEXT,
            status VARCHAR(20) DEFAULT 'pending',
            priority VARCHAR(10) DEFAULT 'medium',
            due_at TIMESTAMPTZ,
            recurrence TEXT,
            tags TEXT[] DEFAULT '{}',
            source VARCHAR(50) DEFAULT 'builtin',
            source_id TEXT,
            assignee TEXT,
            parent_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
            user_id TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- events
        CREATE TABLE IF NOT EXISTS events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            title TEXT NOT NULL,
            description TEXT,
            start_at TIMESTAMPTZ NOT NULL,
            end_at TIMESTAMPTZ NOT NULL,
            all_day BOOLEAN DEFAULT FALSE,
            location TEXT,
            attendees TEXT[] DEFAULT '{}',
            reminder_minutes INT[] DEFAULT '{15}',
            recurrence TEXT,
            source VARCHAR(50) DEFAULT 'builtin',
            source_id TEXT,
            user_id TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- contacts
        CREATE TABLE IF NOT EXISTS contacts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            platform_ids JSONB DEFAULT '{}',
            organization TEXT,
            tags TEXT[] DEFAULT '{}',
            notes TEXT,
            user_id TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- files_meta
        CREATE TABLE IF NOT EXISTS files_meta (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            path_or_url TEXT NOT NULL,
            mime_type TEXT,
            size_bytes BIGINT DEFAULT 0,
            source VARCHAR(50) DEFAULT 'local',
            source_id TEXT,
            parent_folder TEXT,
            user_id TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- sync_state
        CREATE TABLE IF NOT EXISTS sync_state (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            adapter_domain VARCHAR(50) NOT NULL,
            adapter_source VARCHAR(50) NOT NULL,
            user_id TEXT NOT NULL,
            last_synced_at TIMESTAMPTZ,
            sync_token TEXT,
            UNIQUE(adapter_domain, adapter_source, user_id)
        );

        -- sync_conflicts
        CREATE TABLE IF NOT EXISTS sync_conflicts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_table VARCHAR(50) NOT NULL,
            entity_id UUID NOT NULL,
            local_data JSONB NOT NULL,
            remote_data JSONB NOT NULL,
            resolution VARCHAR(20) NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- bg_jobs
        CREATE TABLE IF NOT EXISTS bg_jobs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            celery_task_id VARCHAR(255),
            title VARCHAR(200) NOT NULL,
            description TEXT DEFAULT '',
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            job_type VARCHAR(20) NOT NULL DEFAULT 'single',
            "user" VARCHAR(100) DEFAULT '',
            channel VARCHAR(200) DEFAULT '',
            platform VARCHAR(20) DEFAULT 'web',
            progress JSONB DEFAULT '{"last_completed_step": 0, "total_steps": 0, "message": "", "percentage": 0}',
            result TEXT,
            error TEXT,
            execution_plan JSONB DEFAULT '[]',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            metadata JSONB DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_bg_jobs_status ON bg_jobs(status);
        CREATE INDEX IF NOT EXISTS idx_bg_jobs_user ON bg_jobs("user");
        CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON tasks(user_id, status);
        CREATE INDEX IF NOT EXISTS idx_tasks_due_at ON tasks(due_at) WHERE status = 'pending';
        CREATE INDEX IF NOT EXISTS idx_events_user_time ON events(user_id, start_at);
        CREATE INDEX IF NOT EXISTS idx_contacts_user ON contacts(user_id);
        CREATE INDEX IF NOT EXISTS idx_files_meta_user_source ON files_meta(user_id, source);

        -- v2 memory tables (from plugins/builtin/memory)

        -- v2_working_memory
        CREATE TABLE IF NOT EXISTS v2_working_memory (
            session_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value JSONB NOT NULL,
            expires_at TIMESTAMPTZ,
            PRIMARY KEY (session_id, key)
        );

        -- v2_episodic_memory
        CREATE TABLE IF NOT EXISTS v2_episodic_memory (
            id SERIAL PRIMARY KEY,
            session_id TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            keywords TEXT[] NOT NULL DEFAULT '{}',
            timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            importance FLOAT NOT NULL DEFAULT 0.5,
            metadata JSONB NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_v2_episodic_session
            ON v2_episodic_memory(session_id);

        -- v2_semantic_memory
        CREATE TABLE IF NOT EXISTS v2_semantic_memory (
            id SERIAL PRIMARY KEY,
            subject TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object TEXT NOT NULL,
            confidence FLOAT NOT NULL DEFAULT 1.0,
            metadata JSONB NOT NULL DEFAULT '{}',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(subject, predicate)
        );

        -- v2_conversations
        CREATE TABLE IF NOT EXISTS v2_conversations (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            channel TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            message_count INT DEFAULT 0,
            total_tokens INT DEFAULT 0
        );

        -- v2_conversation_messages
        CREATE TABLE IF NOT EXISTS v2_conversation_messages (
            id SERIAL PRIMARY KEY,
            session_id TEXT REFERENCES v2_conversations(session_id) ON DELETE CASCADE,
            seq INT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_calls JSONB,
            tool_call_id TEXT,
            name TEXT,
            is_meta BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_conv_msg_session
            ON v2_conversation_messages(session_id, seq);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS v2_conversation_messages CASCADE;
        DROP TABLE IF EXISTS v2_conversations CASCADE;
        DROP TABLE IF EXISTS v2_semantic_memory CASCADE;
        DROP TABLE IF EXISTS v2_episodic_memory CASCADE;
        DROP TABLE IF EXISTS v2_working_memory CASCADE;
        DROP TABLE IF EXISTS bg_jobs CASCADE;
        DROP TABLE IF EXISTS sync_conflicts CASCADE;
        DROP TABLE IF EXISTS sync_state CASCADE;
        DROP TABLE IF EXISTS files_meta CASCADE;
        DROP TABLE IF EXISTS contacts CASCADE;
        DROP TABLE IF EXISTS events CASCADE;
        DROP TABLE IF EXISTS tasks CASCADE;
        DROP TABLE IF EXISTS conversations CASCADE;
        DROP TABLE IF EXISTS mcp_servers CASCADE;
        DROP TABLE IF EXISTS settings CASCADE;
        DROP TABLE IF EXISTS kg_relations CASCADE;
        DROP TABLE IF EXISTS kg_entities CASCADE;
        DROP TABLE IF EXISTS episodic_notes CASCADE;
        DROP TABLE IF EXISTS audit_log CASCADE;
    """)
