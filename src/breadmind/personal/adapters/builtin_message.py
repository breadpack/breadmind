"""Built-in Message adapter for searching conversation history."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from breadmind.personal.adapters.base import ServiceAdapter, SyncResult
from breadmind.personal.models import Message

logger = logging.getLogger(__name__)


class BuiltinMessageAdapter(ServiceAdapter):
    """Searches messages from the conversations table."""

    def __init__(self, db: Any) -> None:
        self._db = db

    @property
    def domain(self) -> str:
        return "message"

    @property
    def source(self) -> str:
        return "builtin"

    async def authenticate(self, credentials: dict) -> bool:
        return True

    async def list_items(
        self, filters: dict | None = None, limit: int = 50,
    ) -> list[Message]:
        """Search messages by keyword, user, or channel.

        Filters: query (text search), user_id, channel, platform, after (datetime).
        """
        if not self._db:
            return []
        filters = filters or {}
        query_text = filters.get("query", "")
        user_id = filters.get("user_id", "")

        # Search in conversations table (messages is JSONB array)
        sql = """
            SELECT session_id, user_id, channel,
                   jsonb_array_elements(messages) as msg
            FROM conversations
            WHERE user_id = $1
        """
        params: list[Any] = [user_id]
        idx = 2

        if filters.get("channel"):
            sql += f" AND channel = ${idx}"
            params.append(filters["channel"])
            idx += 1

        try:
            async with self._db.acquire() as conn:
                rows = await conn.fetch(sql, *params)
        except Exception:
            logger.exception("Message search failed")
            return []

        # Filter by query text in Python (JSONB text search is complex)
        messages: list[Message] = []
        for row in rows:
            msg_data = row["msg"] if isinstance(row["msg"], dict) else {}
            content = msg_data.get("content", "")
            role = msg_data.get("role", "")

            if query_text and query_text.lower() not in content.lower():
                continue
            if role == "system":
                continue  # Skip system messages

            messages.append(Message(
                id=f"{row['session_id']}:{len(messages)}",
                content=content[:500],  # Truncate long messages
                sender=role,
                channel=row.get("channel", ""),
                platform="web",
                user_id=row.get("user_id", ""),
                timestamp=datetime.now(timezone.utc),
            ))

            if len(messages) >= limit:
                break

        return messages

    async def get_item(self, source_id: str) -> Message | None:
        return None  # Individual message lookup not supported

    async def create_item(self, entity: Message) -> str:
        return ""  # Messages are created through the chat flow, not directly

    async def update_item(self, source_id: str, changes: dict) -> bool:
        return False

    async def delete_item(self, source_id: str) -> bool:
        return False

    async def sync(
        self, since: datetime | None = None,
    ) -> SyncResult:
        return SyncResult(
            created=[], updated=[], deleted=[], errors=[],
            synced_at=datetime.now(timezone.utc),
        )
