"""Insert helper for the ``kb_audit_log`` table."""
from __future__ import annotations

import json
from typing import Any


async def audit_log(
    db,
    actor: str,
    action: str,
    subject_type: str | None = None,
    subject_id: str | None = None,
    project_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Insert one audit row. Fire-and-forget; errors propagate."""
    md_json = json.dumps(metadata) if metadata is not None else None
    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO kb_audit_log (
                actor, action, subject_type, subject_id,
                project_id, metadata
            ) VALUES ($1, $2, $3, $4, $5::uuid, $6::jsonb)
            """,
            actor,
            action,
            subject_type,
            subject_id,
            project_id,
            md_json,
        )
