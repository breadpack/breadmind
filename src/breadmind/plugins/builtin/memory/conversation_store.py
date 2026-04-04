"""Conversation persistence store.

Saves and restores multi-turn conversations to PostgreSQL or local JSONL files.
asyncpg is an optional dependency -- imported lazily.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
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
        self._file_dir = Path(file_dir) if file_dir else None
        self._tables_created = False

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

    # ── Public API ──────────────────────────────────────────────────

    async def save_message(self, session_id: str, message: Message) -> None:
        """Append a single message to a conversation."""
        if self._backend and self._backend._pool:
            await self._pg_append_message(session_id, message)
        elif self._file_dir:
            self._file_append_message(session_id, message)

    async def save_conversation(
        self,
        session_id: str,
        messages: list[Message],
        meta: ConversationMeta,
    ) -> None:
        """Save (or overwrite) a full conversation with metadata."""
        if self._backend and self._backend._pool:
            await self._pg_save_conversation(session_id, messages, meta)
        elif self._file_dir:
            self._file_save_conversation(session_id, messages, meta)

    async def load_conversation(self, session_id: str) -> list[Message] | None:
        """Load messages for a session. Returns None if not found."""
        if self._backend and self._backend._pool:
            return await self._pg_load_conversation(session_id)
        if self._file_dir:
            return self._file_load_conversation(session_id)
        return None

    async def list_conversations(
        self, user: str | None = None, limit: int = 20,
    ) -> list[ConversationMeta]:
        """List recent conversations, newest first."""
        if self._backend and self._backend._pool:
            return await self._pg_list_conversations(user, limit)
        if self._file_dir:
            return self._file_list_conversations(user, limit)
        return []

    async def delete_conversation(self, session_id: str) -> bool:
        """Delete a conversation. Returns True if it existed."""
        if self._backend and self._backend._pool:
            return await self._pg_delete_conversation(session_id)
        if self._file_dir:
            return self._file_delete_conversation(session_id)
        return False

    async def search_conversations(
        self, query: str, limit: int = 10,
    ) -> list[ConversationMeta]:
        """Search conversations by title/content."""
        if self._backend and self._backend._pool:
            return await self._pg_search_conversations(query, limit)
        if self._file_dir:
            return self._file_search_conversations(query, limit)
        return []

    # ── PG implementation ───────────────────────────────────────────

    async def _pg_append_message(self, session_id: str, message: Message) -> None:
        pool = self._backend._pool  # type: ignore[union-attr]
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

    async def _pg_save_conversation(
        self, session_id: str, messages: list[Message], meta: ConversationMeta,
    ) -> None:
        pool = self._backend._pool  # type: ignore[union-attr]
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

    async def _pg_load_conversation(self, session_id: str) -> list[Message] | None:
        pool = self._backend._pool  # type: ignore[union-attr]
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

    async def _pg_list_conversations(
        self, user: str | None, limit: int,
    ) -> list[ConversationMeta]:
        pool = self._backend._pool  # type: ignore[union-attr]
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

    async def _pg_delete_conversation(self, session_id: str) -> bool:
        pool = self._backend._pool  # type: ignore[union-attr]
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM v2_conversations WHERE session_id = $1",
                session_id,
            )
            # asyncpg returns "DELETE N"
            return result != "DELETE 0"

    async def _pg_search_conversations(
        self, query: str, limit: int,
    ) -> list[ConversationMeta]:
        pool = self._backend._pool  # type: ignore[union-attr]
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

    # ── File implementation ─────────────────────────────────────────

    def _ensure_file_dir(self) -> Path:
        assert self._file_dir is not None
        self._file_dir.mkdir(parents=True, exist_ok=True)
        return self._file_dir

    def _msg_file(self, session_id: str) -> Path:
        return self._ensure_file_dir() / f"{session_id}.jsonl"

    def _index_file(self) -> Path:
        return self._ensure_file_dir() / "index.json"

    def _read_index(self) -> list[dict[str, Any]]:
        idx = self._index_file()
        if not idx.exists():
            return []
        return json.loads(idx.read_text(encoding="utf-8"))

    def _write_index(self, entries: list[dict[str, Any]]) -> None:
        self._index_file().write_text(
            json.dumps(entries, default=str, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _file_append_message(self, session_id: str, message: Message) -> None:
        path = self._msg_file(session_id)
        line = json.dumps(_message_to_dict(message), default=str, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _file_save_conversation(
        self, session_id: str, messages: list[Message], meta: ConversationMeta,
    ) -> None:
        # Write messages
        path = self._msg_file(session_id)
        lines = [
            json.dumps(_message_to_dict(m), default=str, ensure_ascii=False)
            for m in messages
        ]
        path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")

        # Update index
        entries = self._read_index()
        meta_dict = _meta_to_dict(meta)
        entries = [e for e in entries if e["session_id"] != session_id]
        entries.insert(0, meta_dict)
        self._write_index(entries)

    def _file_load_conversation(self, session_id: str) -> list[Message] | None:
        path = self._msg_file(session_id)
        if not path.exists():
            return None
        messages: list[Message] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            messages.append(_dict_to_message(json.loads(line)))
        return messages or None

    def _file_list_conversations(
        self, user: str | None, limit: int,
    ) -> list[ConversationMeta]:
        entries = self._read_index()
        if user:
            entries = [e for e in entries if e.get("user") == user]
        # Already sorted newest-first by save_conversation insert order
        return [_dict_to_meta(e) for e in entries[:limit]]

    def _file_delete_conversation(self, session_id: str) -> bool:
        path = self._msg_file(session_id)
        existed = path.exists()
        if existed:
            path.unlink()
        entries = self._read_index()
        new_entries = [e for e in entries if e["session_id"] != session_id]
        if len(new_entries) != len(entries):
            self._write_index(new_entries)
            existed = True
        return existed

    def _file_search_conversations(
        self, query: str, limit: int,
    ) -> list[ConversationMeta]:
        query_lower = query.lower()
        entries = self._read_index()
        results: list[ConversationMeta] = []
        for entry in entries:
            if query_lower in entry.get("title", "").lower():
                results.append(_dict_to_meta(entry))
                if len(results) >= limit:
                    break
        return results
