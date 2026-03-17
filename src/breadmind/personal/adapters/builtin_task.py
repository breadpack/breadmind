# src/breadmind/personal/adapters/builtin_task.py
"""Built-in Task adapter backed by PostgreSQL."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from breadmind.personal.adapters.base import ServiceAdapter, SyncResult
from breadmind.personal.models import Task


class BuiltinTaskAdapter(ServiceAdapter):
    def __init__(self, db: Any) -> None:
        self._db = db

    @property
    def domain(self) -> str:
        return "task"

    @property
    def source(self) -> str:
        return "builtin"

    async def authenticate(self, credentials: dict) -> bool:
        return True

    async def list_items(self, filters: dict | None = None, limit: int = 50) -> list[Task]:
        filters = filters or {}
        user_id = filters.get("user_id", "")
        query = "SELECT * FROM tasks WHERE user_id = $1"
        params: list[Any] = [user_id]
        idx = 2
        if "status" in filters:
            query += f" AND status = ${idx}"
            params.append(filters["status"])
            idx += 1
        if "priority" in filters:
            query += f" AND priority = ${idx}"
            params.append(filters["priority"])
            idx += 1
        if "due_before" in filters:
            query += f" AND due_at IS NOT NULL AND due_at <= ${idx}"
            params.append(filters["due_before"])
            idx += 1
        if "tags" in filters:
            query += f" AND tags && ${idx}"
            params.append(filters["tags"])
            idx += 1
        query += f" ORDER BY created_at DESC LIMIT ${idx}"
        params.append(limit)
        async with self._db.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [self._row_to_task(row) for row in rows]

    async def get_item(self, source_id: str) -> Task | None:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", source_id)
        return self._row_to_task(row) if row else None

    async def create_item(self, entity: Task) -> str:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO tasks (title, description, status, priority, due_at,
                   recurrence, tags, source, source_id, assignee, parent_id, user_id)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                   RETURNING id""",
                entity.title, entity.description, entity.status, entity.priority,
                entity.due_at, entity.recurrence, entity.tags, entity.source,
                entity.source_id, entity.assignee, entity.parent_id, entity.user_id,
            )
        return str(row["id"])

    async def update_item(self, source_id: str, changes: dict) -> bool:
        if not changes:
            return False
        allowed = {"title", "description", "status", "priority", "due_at", "recurrence", "tags", "assignee"}
        filtered = {k: v for k, v in changes.items() if k in allowed}
        if not filtered:
            return False
        filtered["updated_at"] = datetime.now(timezone.utc)
        sets = [f"{k} = ${i+2}" for i, k in enumerate(filtered)]
        query = f"UPDATE tasks SET {', '.join(sets)} WHERE id = $1"
        params = [source_id, *filtered.values()]
        async with self._db.acquire() as conn:
            await conn.execute(query, *params)
        return True

    async def delete_item(self, source_id: str) -> bool:
        async with self._db.acquire() as conn:
            await conn.execute("DELETE FROM tasks WHERE id = $1", source_id)
        return True

    async def sync(self, since: datetime | None = None) -> SyncResult:
        return SyncResult(created=[], updated=[], deleted=[], errors=[], synced_at=datetime.now(timezone.utc))

    @staticmethod
    def _row_to_task(row: dict) -> Task:
        return Task(
            id=str(row["id"]), title=row["title"], description=row.get("description"),
            status=row.get("status", "pending"), priority=row.get("priority", "medium"),
            due_at=row.get("due_at"), recurrence=row.get("recurrence"),
            tags=row.get("tags", []), source=row.get("source", "builtin"),
            source_id=row.get("source_id"), assignee=row.get("assignee"),
            parent_id=str(row["parent_id"]) if row.get("parent_id") else None,
            user_id=row.get("user_id", ""),
            created_at=row.get("created_at", datetime.now(timezone.utc)),
            updated_at=row.get("updated_at", datetime.now(timezone.utc)),
        )
