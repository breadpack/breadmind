"""Database schema for distributed agent network."""

AGENT_NETWORK_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL,
    host VARCHAR(256) NOT NULL,
    status VARCHAR(20) DEFAULT 'registering',
    environment JSONB,
    cert_fingerprint VARCHAR(64),
    cert_expires_at TIMESTAMPTZ,
    last_heartbeat TIMESTAMPTZ,
    registered_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);

CREATE TABLE IF NOT EXISTS agent_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) UNIQUE NOT NULL,
    definition JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_role_assignments (
    agent_id UUID REFERENCES agents(id) ON DELETE CASCADE,
    role_id UUID REFERENCES agent_roles(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (agent_id, role_id)
);

CREATE TABLE IF NOT EXISTS agent_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES agents(id),
    role_id UUID REFERENCES agent_roles(id),
    idempotency_key VARCHAR(128),
    type VARCHAR(20) NOT NULL,
    params JSONB,
    status VARCHAR(20) DEFAULT 'pending',
    result JSONB,
    metrics JSONB,
    trace_id UUID,
    created_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_agent_tasks_agent_status ON agent_tasks(agent_id, status);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_created ON agent_tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_idempotency ON agent_tasks(idempotency_key);

CREATE TABLE IF NOT EXISTS agent_certificates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES agents(id) ON DELETE CASCADE,
    fingerprint VARCHAR(64) NOT NULL,
    issued_at TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT true
);
"""

WORKER_LOCAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS offline_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    result TEXT NOT NULL,
    needs_llm INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    synced_at TEXT
);

CREATE TABLE IF NOT EXISTS task_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    idempotency_key TEXT,
    status TEXT NOT NULL,
    result TEXT,
    executed_at TEXT DEFAULT (datetime('now'))
);
"""
