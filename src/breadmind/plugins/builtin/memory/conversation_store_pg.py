"""PostgreSQL backend for conversation storage."""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from breadmind.core.protocols.provider import Message, ToolCallRequest

if TYPE_CHECKING:
    from breadmind.plugins.builtin.memory.conversation_store import ConversationMeta
    from breadmind.plugins.builtin.memory.pg_backend import PgMemoryBackend

logger = logging.getLogger(__name__)


class ConversationStorePg:
    """PostgreSQL implementation of conversation storage operations."""

    def __init__(self, backend: PgMemoryBackend) -> None:
        self._backend = backend

    @property
    def _pool(self):
        return self._backend._pool

    async def append_message(self, session_id: str, message: Message) -> None:
        pool = self._pool
        async with pool.acquire() as conn:
            seq = await conn.fetchval(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM v2_conversation_messages "
                "WHERE session_id = $1",
                session_id,
            )
            tc_json = (
                json.dumps(
                    [{"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                     for tc in message.tool_calls],
                    default=str,
                )
                if message.tool_calls else None
            )
            await conn.execute(
                """
                INSERT INTO v2_conversation_messages
                    (session_id, seq, role, content, tool_calls, tool_call_id, name, is_meta)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8)
                """,
                session_id, seq, message.role, message.content,
                tc_json, message.tool_call_id, message.name, message.is_meta,
            )
            await conn.execute(
                """
                UPDATE v2_conversations
                SET message_count = message_count + 1, updated_at = NOW()
                WHERE session_id = $1
                """,
                session_id,
            )

    async def save_conversation(
        self, session_id: str, messages: list[Message], meta: ConversationMeta,
    ) -> None:
        pool = self._pool
        async with pool.acquire() as conn:
            # Upsert meta
            await conn.execute(
                """
                INSERT INTO v2_conversations
                    (session_id, user_id, channel, title, created_at, updated_at,
                     message_count, total_tokens)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (session_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    updated_at = EXCLUDED.updated_at,
                    message_count = EXCLUDED.message_count,
                    total_tokens = EXCLUDED.total_tokens
                """,
                meta.session_id, meta.user, meta.channel, meta.title,
                meta.created_at, meta.updated_at,
                meta.message_count, meta.total_tokens,
            )
            # Replace messages
            await conn.execute(
                "DELETE FROM v2_conversation_messages WHERE session_id = $1",
                session_id,
            )
            for seq, msg in enumerate(messages, 1):
                tc_json = (
                    json.dumps(
                        [{"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                         for tc in msg.tool_calls],
                        default=str,
                    )
                    if msg.tool_calls else None
                )
                await conn.execute(
                    """
                    INSERT INTO v2_conversation_messages
                        (session_id, seq, role, content, tool_calls, tool_call_id,
                         name, is_meta)
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8)
                    """,
                    session_id, seq, msg.role, msg.content,
                    tc_json, msg.tool_call_id, msg.name, msg.is_meta,
                )

    async def load_conversation(self, session_id: str) -> list[Message] | None:
        pool = self._pool
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT role, content, tool_calls, tool_call_id, name, is_meta
                FROM v2_conversation_messages
                WHERE session_id = $1
                ORDER BY seq ASC
                """,
                session_id,
            )
            if not rows:
                return None
            messages: list[Message] = []
            for row in rows:
                tc_raw = row["tool_calls"]
                if tc_raw:
                    if isinstance(tc_raw, str):
                        tc_raw = json.loads(tc_raw)
                    tool_calls = [
                        ToolCallRequest(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                        for tc in tc_raw
                    ]
                else:
                    tool_calls = []
                messages.append(Message(
                    role=row["role"],
                    content=row["content"],
                    tool_calls=tool_calls,
                    tool_call_id=row["tool_call_id"],
                    name=row["name"],
                    is_meta=row["is_meta"] if row["is_meta"] is not None else False,
                ))
            return messages

    async def list_conversations(
        self, user: str | None, limit: int,
    ) -> list[ConversationMeta]:
        pool = self._pool
        async with pool.acquire() as conn:
            if user:
                rows = await conn.fetch(
                    """
                    SELECT session_id, user_id, channel, title,
                           created_at, updated_at, message_count, total_tokens
                    FROM v2_conversations
                    WHERE user_id = $1
                    ORDER BY updated_at DESC
                    LIMIT $2
                    """,
                    user, limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT session_id, user_id, channel, title,
                           created_at, updated_at, message_count, total_tokens
                    FROM v2_conversations
                    ORDER BY updated_at DESC
                    LIMIT $1
                    """,
                    limit,
                )
            return [self._row_to_meta(r) for r in rows]

    async def delete_conversation(self, session_id: str) -> bool:
        pool = self._pool
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM v2_conversations WHERE session_id = $1",
                session_id,
            )
            # asyncpg returns "DELETE N"
            return result != "DELETE 0"

    async def search_conversations(
        self, query: str, limit: int,
    ) -> list[ConversationMeta]:
        pool = self._pool
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT c.session_id, c.user_id, c.channel, c.title,
                       c.created_at, c.updated_at, c.message_count, c.total_tokens
                FROM v2_conversations c
                LEFT JOIN v2_conversation_messages m ON c.session_id = m.session_id
                WHERE c.title ILIKE '%' || $1 || '%'
                   OR m.content ILIKE '%' || $1 || '%'
                ORDER BY c.updated_at DESC
                LIMIT $2
                """,
                query, limit,
            )
            return [self._row_to_meta(r) for r in rows]

    @staticmethod
    def _row_to_meta(row) -> ConversationMeta:
        from breadmind.plugins.builtin.memory.conversation_store import ConversationMeta
        return ConversationMeta(
            session_id=row["session_id"],
            user=row["user_id"],
            channel=row["channel"] or "",
            title=row["title"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            message_count=row["message_count"] or 0,
            total_tokens=row["total_tokens"] or 0,
        )
