"""Conversation persistence store.

Saves and restores multi-turn conversations to PostgreSQL or local JSONL files.
asyncpg is an optional dependency -- imported lazily.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from breadmind.core.protocols.provider import Message, ToolCallRequest

if TYPE_CHECKING:
    from breadmind.plugins.builtin.memory.pg_backend import PgMemoryBackend

logger = logging.getLogger(__name__)


# ── Data classes ────────────────────────────────────────────────────


@dataclass
class ConversationMeta:
    """Metadata for a stored conversation."""

    session_id: str
    user: str
    channel: str = ""
    title: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    message_count: int = 0
    total_tokens: int = 0


# ── Serialisation helpers ───────────────────────────────────────────


def _message_to_dict(msg: Message) -> dict[str, Any]:
    """Serialise a Message to a JSON-safe dict."""
    d: dict[str, Any] = {"role": msg.role}
    if msg.content is not None:
        d["content"] = msg.content
    if msg.tool_calls:
        d["tool_calls"] = [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in msg.tool_calls
        ]
    if msg.tool_call_id is not None:
        d["tool_call_id"] = msg.tool_call_id
    if msg.name is not None:
        d["name"] = msg.name
    if msg.is_meta:
        d["is_meta"] = True
    return d


def _dict_to_message(d: dict[str, Any]) -> Message:
    """Deserialise a dict back into a Message."""
    tool_calls = [
        ToolCallRequest(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
        for tc in d.get("tool_calls", [])
    ]
    return Message(
        role=d["role"],
        content=d.get("content"),
        tool_calls=tool_calls,
        tool_call_id=d.get("tool_call_id"),
        name=d.get("name"),
        is_meta=d.get("is_meta", False),
    )


def _meta_to_dict(meta: ConversationMeta) -> dict[str, Any]:
    d = asdict(meta)
    d["created_at"] = meta.created_at.isoformat()
    d["updated_at"] = meta.updated_at.isoformat()
    return d


def _dict_to_meta(d: dict[str, Any]) -> ConversationMeta:
    return ConversationMeta(
        session_id=d["session_id"],
        user=d["user"],
        channel=d.get("channel", ""),
        title=d.get("title", ""),
        created_at=datetime.fromisoformat(d["created_at"]),
        updated_at=datetime.fromisoformat(d["updated_at"]),
        message_count=d.get("message_count", 0),
        total_tokens=d.get("total_tokens", 0),
    )


# ── Store ───────────────────────────────────────────────────────────


class ConversationStore:
    """Conversation persistence store. PG backend or filesystem."""

    _CREATE_TABLES_SQL = """
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
    """

    def __init__(
        self,
        backend: PgMemoryBackend | None = None,
        file_dir: str | None = None,
    ) -> None:
        self._backend = backend
        self._tables_created = False

        # Lazily initialise storage delegates
        self._pg: ConversationStorePg | None = None
        self._file: ConversationStoreFile | None = None

        if backend is not None:
            from breadmind.plugins.builtin.memory.conversation_store_pg import (
                ConversationStorePg,
            )
            self._pg = ConversationStorePg(backend)

        if file_dir is not None:
            from breadmind.plugins.builtin.memory.conversation_store_file import (
                ConversationStoreFile,
            )
            self._file = ConversationStoreFile(file_dir)

    # ── Initialisation ──────────────────────────────────────────────

    async def ensure_tables(self) -> None:
        """Create PG tables if they do not exist yet."""
        if self._backend is None or self._tables_created:
            return
        pool = self._backend._pool
        if pool is None:
            return
        async with pool.acquire() as conn:
            await conn.execute(self._CREATE_TABLES_SQL)
        self._tables_created = True

    # ── Helpers ─────────────────────────────────────────────────────

    def _has_pg(self) -> bool:
        return self._pg is not None and self._backend is not None and self._backend._pool is not None

    # ── Public API ──────────────────────────────────────────────────

    async def save_message(self, session_id: str, message: Message) -> None:
        """Append a single message to a conversation."""
        if self._has_pg():
            await self._pg.append_message(session_id, message)  # type: ignore[union-attr]
        elif self._file:
            self._file.append_message(session_id, message)

    async def save_conversation(
        self,
        session_id: str,
        messages: list[Message],
        meta: ConversationMeta,
    ) -> None:
        """Save (or overwrite) a full conversation with metadata."""
        if self._has_pg():
            await self._pg.save_conversation(session_id, messages, meta)  # type: ignore[union-attr]
        elif self._file:
            self._file.save_conversation(session_id, messages, meta)

    async def load_conversation(self, session_id: str) -> list[Message] | None:
        """Load messages for a session. Returns None if not found."""
        if self._has_pg():
            return await self._pg.load_conversation(session_id)  # type: ignore[union-attr]
        if self._file:
            return self._file.load_conversation(session_id)
        return None

    async def list_conversations(
        self, user: str | None = None, limit: int = 20,
    ) -> list[ConversationMeta]:
        """List recent conversations, newest first."""
        if self._has_pg():
            return await self._pg.list_conversations(user, limit)  # type: ignore[union-attr]
        if self._file:
            return self._file.list_conversations(user, limit)
        return []

    async def delete_conversation(self, session_id: str) -> bool:
        """Delete a conversation. Returns True if it existed."""
        if self._has_pg():
            return await self._pg.delete_conversation(session_id)  # type: ignore[union-attr]
        if self._file:
            return self._file.delete_conversation(session_id)
        return False

    async def search_conversations(
        self, query: str, limit: int = 10,
    ) -> list[ConversationMeta]:
        """Search conversations by title/content."""
        if self._has_pg():
            return await self._pg.search_conversations(query, limit)  # type: ignore[union-attr]
        if self._file:
            return self._file.search_conversations(query, limit)
        return []
