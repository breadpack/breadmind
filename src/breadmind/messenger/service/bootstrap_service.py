"""Default agent bootstrap on workspace creation."""
from __future__ import annotations
import json
from uuid import UUID, uuid4


_DEFAULT_AGENT_CONFIG = {
    "agent_class": "default",
    "persona": "조직 지식 관리 도우미",
    "tools_enabled": ["kb.query", "web.search", "code_delegate"],
    "llm": {
        "provider": "anthropic",
        "model": "claude-opus-4-7",
        "fallback": "claude-haiku-4-5",
    },
    "episodic_recall": {"enabled": True, "top_k": 5, "trigger": "turn|tool"},
    "self_review": True,
    "approval_required_for": [
        "destructive_db_op",
        "external_api_paid",
        "email_send",
    ],
    "memory_normalize": True,
}


async def bootstrap_default_agent(db, *, workspace_id: UUID) -> UUID:
    agent_id = uuid4()
    await db.execute(
        """INSERT INTO workspace_users
              (id, workspace_id, email, kind, display_name, real_name, role, agent_config)
           VALUES ($1, $2, $3, 'agent', 'BreadMind', 'BreadMind Default Agent',
                   'admin', $4::jsonb)""",
        agent_id, workspace_id,
        f"breadmind+{workspace_id}@breadmind.local",
        json.dumps(_DEFAULT_AGENT_CONFIG),
    )
    return agent_id
