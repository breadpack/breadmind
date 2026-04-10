"""Event store for Durable Task Flow.

Responsibilities:
- Append events with sequence assignment (transactional)
- Update projection tables (flows, flow_steps)
- Replay events for a flow
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from breadmind.flow.events import EventType, FlowEvent
from breadmind.storage.database import Database


class FlowEventStore:
    """Append-only event log with projection updates.

    All writes go through :meth:`append`, which:

    1. Locks the per-flow event tail and assigns the next sequence number.
    2. Inserts the event row into ``flow_events``.
    3. Applies the projection update to ``flows`` / ``flow_steps``.

    The entire sequence runs inside a single transaction so either the
    event is persisted together with its projection or neither is.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def append(self, event: FlowEvent) -> FlowEvent:
        async with self._db.acquire() as conn:
            async with conn.transaction():
                # Serialize concurrent appends for the same flow with a
                # per-flow transaction-scoped advisory lock. We cannot use
                # ``SELECT MAX(seq) ... FOR UPDATE`` because PostgreSQL
                # forbids row locks on aggregate queries.
                await conn.execute(
                    "SELECT pg_advisory_xact_lock("
                    "('x' || substr(md5($1::text), 1, 16))::bit(64)::bigint)",
                    str(event.flow_id),
                )
                row = await conn.fetchrow(
                    "SELECT COALESCE(MAX(seq), 0) AS max_seq "
                    "FROM flow_events WHERE flow_id = $1",
                    event.flow_id,
                )
                next_seq = int(row["max_seq"]) + 1
                event.seq = next_seq
                if event.created_at.tzinfo is None:
                    event.created_at = event.created_at.replace(tzinfo=timezone.utc)
                await conn.execute(
                    """
                    INSERT INTO flow_events (
                        flow_id, seq, event_type, payload, actor,
                        created_at, schema_version
                    )
                    VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)
                    """,
                    event.flow_id,
                    event.seq,
                    event.event_type.value,
                    json.dumps(event.payload),
                    event.actor.value,
                    event.created_at,
                    event.schema_version,
                )
                await self._apply_projection(conn, event)
        return event

    async def _apply_projection(self, conn: Any, event: FlowEvent) -> None:
        p = event.payload
        etype = event.event_type
        if etype == EventType.FLOW_CREATED:
            await conn.execute(
                """
                INSERT INTO flows (
                    id, title, description, user_id, status, origin, last_event_seq
                )
                VALUES ($1, $2, $3, $4, 'pending', $5, $6)
                ON CONFLICT (id) DO NOTHING
                """,
                event.flow_id,
                p["title"],
                p.get("description", ""),
                p["user_id"],
                p.get("origin", "chat"),
                event.seq,
            )
        elif etype == EventType.DAG_PROPOSED:
            for step in p.get("steps", []):
                await conn.execute(
                    """
                    INSERT INTO flow_steps (
                        flow_id, step_id, title, tool, args, depends_on, status
                    )
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6, 'pending')
                    ON CONFLICT (flow_id, step_id) DO NOTHING
                    """,
                    event.flow_id,
                    step["id"],
                    step["title"],
                    step.get("tool"),
                    json.dumps(step.get("args", {})),
                    step.get("depends_on", []),
                )
            await self._touch_flow(conn, event)
        elif etype == EventType.STEP_QUEUED:
            await conn.execute(
                "UPDATE flow_steps SET status = 'queued' "
                "WHERE flow_id = $1 AND step_id = $2",
                event.flow_id,
                p["step_id"],
            )
            await self._touch_flow(conn, event)
        elif etype == EventType.STEP_STARTED:
            await conn.execute(
                """
                UPDATE flow_steps
                SET status = 'running',
                    started_at = $3,
                    attempt = attempt + 1
                WHERE flow_id = $1 AND step_id = $2
                """,
                event.flow_id,
                p["step_id"],
                datetime.now(timezone.utc),
            )
            await conn.execute(
                "UPDATE flows SET status = 'running', updated_at = now(), "
                "last_event_seq = $2 WHERE id = $1",
                event.flow_id,
                event.seq,
            )
        elif etype == EventType.STEP_COMPLETED:
            await conn.execute(
                """
                UPDATE flow_steps
                SET status = 'completed',
                    completed_at = $3,
                    result = $4::jsonb
                WHERE flow_id = $1 AND step_id = $2
                """,
                event.flow_id,
                p["step_id"],
                datetime.now(timezone.utc),
                json.dumps(p.get("result")),
            )
            await self._touch_flow(conn, event)
        elif etype == EventType.STEP_FAILED:
            await conn.execute(
                """
                UPDATE flow_steps
                SET status = 'failed',
                    completed_at = $3,
                    error = $4
                WHERE flow_id = $1 AND step_id = $2
                """,
                event.flow_id,
                p["step_id"],
                datetime.now(timezone.utc),
                p.get("error", ""),
            )
            await self._touch_flow(conn, event)
        elif etype == EventType.FLOW_COMPLETED:
            await conn.execute(
                """
                UPDATE flows
                SET status = 'completed',
                    updated_at = now(),
                    last_event_seq = $2,
                    summary = $3::jsonb
                WHERE id = $1
                """,
                event.flow_id,
                event.seq,
                json.dumps(p.get("summary", {})),
            )
        elif etype == EventType.FLOW_FAILED:
            await conn.execute(
                "UPDATE flows SET status = 'failed', updated_at = now(), "
                "last_event_seq = $2 WHERE id = $1",
                event.flow_id,
                event.seq,
            )
        elif etype == EventType.FLOW_PAUSED:
            await conn.execute(
                "UPDATE flows SET status = 'paused', updated_at = now(), "
                "last_event_seq = $2 WHERE id = $1",
                event.flow_id,
                event.seq,
            )
        elif etype == EventType.FLOW_RESUMED:
            await conn.execute(
                "UPDATE flows SET status = 'running', updated_at = now(), "
                "last_event_seq = $2 WHERE id = $1",
                event.flow_id,
                event.seq,
            )
        elif etype == EventType.FLOW_CANCELLED:
            await conn.execute(
                "UPDATE flows SET status = 'cancelled', updated_at = now(), "
                "last_event_seq = $2 WHERE id = $1",
                event.flow_id,
                event.seq,
            )
        elif etype == EventType.ESCALATION_RAISED:
            await conn.execute(
                "UPDATE flows SET status = 'escalated', updated_at = now(), "
                "last_event_seq = $2 WHERE id = $1",
                event.flow_id,
                event.seq,
            )
        else:
            await self._touch_flow(conn, event)

    async def _touch_flow(self, conn: Any, event: FlowEvent) -> None:
        await conn.execute(
            "UPDATE flows SET updated_at = now(), last_event_seq = $2 "
            "WHERE id = $1",
            event.flow_id,
            event.seq,
        )

    async def replay(self, flow_id: UUID, from_seq: int = 0) -> list[FlowEvent]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT flow_id, seq, event_type, payload, actor,
                       created_at, schema_version
                FROM flow_events
                WHERE flow_id = $1 AND seq > $2
                ORDER BY seq
                """,
                flow_id,
                from_seq,
            )
        events: list[FlowEvent] = []
        for r in rows:
            payload = r["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            events.append(
                FlowEvent.from_dict(
                    {
                        "flow_id": str(r["flow_id"]),
                        "seq": r["seq"],
                        "event_type": r["event_type"],
                        "payload": payload,
                        "actor": r["actor"],
                        "created_at": r["created_at"].isoformat(),
                        "schema_version": r["schema_version"],
                    }
                )
            )
        return events
