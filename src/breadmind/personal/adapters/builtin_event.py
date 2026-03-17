"""Built-in Event adapter backed by PostgreSQL."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from breadmind.personal.adapters.base import ServiceAdapter, SyncResult
from breadmind.personal.models import Event


class BuiltinEventAdapter(ServiceAdapter):
    def __init__(self, db: Any) -> None:
        self._db = db

    @property
    def domain(self) -> str:
        return "event"

    @property
    def source(self) -> str:
        return "builtin"

    async def authenticate(self, credentials: dict) -> bool:
        return True

    async def list_items(self, filters: dict | None = None, limit: int = 50) -> list[Event]:
        filters = filters or {}
        user_id = filters.get("user_id", "")
        query = "SELECT * FROM events WHERE user_id = $1"
        params: list[Any] = [user_id]
        idx = 2
        if "start_after" in filters:
            query += f" AND start_at >= ${idx}"
            params.append(filters["start_after"])
            idx += 1
        if "start_before" in filters:
            query += f" AND start_at <= ${idx}"
            params.append(filters["start_before"])
            idx += 1
        query += f" ORDER BY start_at ASC LIMIT ${idx}"
        params.append(limit)
        async with self._db.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [self._row_to_event(row) for row in rows]

    async def get_item(self, source_id: str) -> Event | None:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM events WHERE id = $1", source_id)
        return self._row_to_event(row) if row else None

    async def create_item(self, entity: Event) -> str:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO events (title, description, start_at, end_at, all_day,
                   location, attendees, reminder_minutes, recurrence, source, source_id, user_id)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                   RETURNING id""",
                entity.title, entity.description, entity.start_at, entity.end_at,
                entity.all_day, entity.location, entity.attendees, entity.reminder_minutes,
                entity.recurrence, entity.source, entity.source_id, entity.user_id,
            )
        return str(row["id"])

    async def update_item(self, source_id: str, changes: dict) -> bool:
        if not changes:
            return False
        allowed = {"title", "description", "start_at", "end_at", "all_day", "location",
                    "attendees", "reminder_minutes", "recurrence"}
        filtered = {k: v for k, v in changes.items() if k in allowed}
        if not filtered:
            return False
        sets = [f"{k} = ${i+2}" for i, k in enumerate(filtered)]
        query = f"UPDATE events SET {', '.join(sets)} WHERE id = $1"
        params = [source_id, *filtered.values()]
        async with self._db.acquire() as conn:
            await conn.execute(query, *params)
        return True

    async def delete_item(self, source_id: str) -> bool:
        async with self._db.acquire() as conn:
            await conn.execute("DELETE FROM events WHERE id = $1", source_id)
        return True

    async def sync(self, since: datetime | None = None) -> SyncResult:
        return SyncResult(created=[], updated=[], deleted=[], errors=[], synced_at=datetime.now(timezone.utc))

    @staticmethod
    def _row_to_event(row: dict) -> Event:
        return Event(
            id=str(row["id"]), title=row["title"], description=row.get("description"),
            start_at=row["start_at"], end_at=row["end_at"],
            all_day=row.get("all_day", False), location=row.get("location"),
            attendees=row.get("attendees", []), reminder_minutes=row.get("reminder_minutes", [15]),
            recurrence=row.get("recurrence"), source=row.get("source", "builtin"),
            source_id=row.get("source_id"), user_id=row.get("user_id", ""),
            created_at=row.get("created_at", datetime.now(timezone.utc)),
        )
