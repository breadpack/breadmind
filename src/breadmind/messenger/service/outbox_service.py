# src/breadmind/messenger/service/outbox_service.py
from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4


async def enqueue_outbox(
    db, *,
    workspace_id: UUID, channel_id: UUID, event_type: str, payload: dict,
    retention_sec: int = 60,
) -> UUID:
    eid = uuid4()
    expires = datetime.now(timezone.utc) + timedelta(seconds=retention_sec)
    await db.execute(
        """INSERT INTO message_outbox
              (id, workspace_id, channel_id, event_type, payload, expires_at)
           VALUES ($1, $2, $3, $4, $5::jsonb, $6)""",
        eid, workspace_id, channel_id, event_type, json.dumps(payload), expires,
    )
    return eid
