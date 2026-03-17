import json
import logging

import asyncpg
from contextlib import asynccontextmanager

from breadmind.storage.models import EpisodicNote, KGEntity, KGRelation

logger = logging.getLogger(__name__)


class Database:
    _has_pgvector: bool = False

    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None
        self._has_pgvector = False

    async def connect(self):
        self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=10)
        await self._migrate()

    async def disconnect(self):
        if self._pool:
            await self._pool.close()

    @asynccontextmanager
    async def acquire(self):
        async with self._pool.acquire() as conn:
            yield conn

    async def _migrate(self):
        async with self.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ DEFAULT NOW(),
                    action TEXT NOT NULL,
                    params JSONB DEFAULT '{}',
                    result TEXT NOT NULL,
                    reason TEXT DEFAULT '',
                    channel TEXT DEFAULT '',
                    "user" TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS episodic_notes (
                    id SERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    keywords TEXT[] DEFAULT '{}',
                    tags TEXT[] DEFAULT '{}',
                    context_description TEXT DEFAULT '',
                    embedding FLOAT8[],
                    linked_note_ids INTEGER[] DEFAULT '{}',
                    decay_weight FLOAT8 DEFAULT 1.0,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS kg_entities (
                    id TEXT PRIMARY KEY,
                    entity_type TEXT,
                    name TEXT,
                    properties JSONB DEFAULT '{}',
                    weight FLOAT8 DEFAULT 1.0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS kg_relations (
                    id SERIAL PRIMARY KEY,
                    source TEXT REFERENCES kg_entities(id),
                    target TEXT REFERENCES kg_entities(id),
                    relation_type TEXT,
                    weight FLOAT8 DEFAULT 1.0,
                    properties JSONB DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value JSONB NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS mcp_servers (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    install_config JSONB NOT NULL,
                    status TEXT DEFAULT 'stopped',
                    installed_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT '',
                    channel TEXT NOT NULL DEFAULT '',
                    title TEXT DEFAULT '',
                    messages JSONB NOT NULL DEFAULT '[]',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    last_active TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);
                CREATE INDEX IF NOT EXISTS idx_conversations_active ON conversations(last_active DESC);
            """)

        # pgvector extension (optional)
        try:
            async with self.acquire() as conn:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
                await conn.execute("""
                    ALTER TABLE episodic_notes
                    ADD COLUMN IF NOT EXISTS embedding_vec vector(384)
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_episodic_embedding_hnsw
                    ON episodic_notes USING hnsw (embedding_vec vector_cosine_ops)
                """)
            self._has_pgvector = True
        except Exception:
            self._has_pgvector = False

    async def insert_audit(self, entry) -> int:
        async with self.acquire() as conn:
            return await conn.fetchval("""
                INSERT INTO audit_log (action, params, result, reason, channel, "user")
                VALUES ($1, $2::jsonb, $3, $4, $5, $6)
                RETURNING id
            """, entry.action, str(entry.params), entry.result,
                entry.reason, entry.channel, entry.user)

    async def health_check(self) -> bool:
        try:
            async with self.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    # --- Episodic Notes ---

    async def save_note(self, note: EpisodicNote) -> int:
        async with self.acquire() as conn:
            note_id = await conn.fetchval("""
                INSERT INTO episodic_notes
                    (content, keywords, tags, context_description, embedding,
                     linked_note_ids, decay_weight, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
            """, note.content, note.keywords, note.tags,
                note.context_description, note.embedding,
                note.linked_note_ids, note.decay_weight,
                note.created_at, note.updated_at)
            return note_id

    async def search_notes_by_keywords(
        self, keywords: list[str], limit: int = 5
    ) -> list[EpisodicNote]:
        async with self.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM episodic_notes
                WHERE keywords && $1::TEXT[]
                ORDER BY decay_weight DESC, created_at DESC
                LIMIT $2
            """, keywords, limit)
            return [self._row_to_note(r) for r in rows]

    async def search_notes_by_tags(
        self, tags: list[str], limit: int = 5
    ) -> list[EpisodicNote]:
        async with self.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM episodic_notes
                WHERE tags && $1::TEXT[]
                ORDER BY decay_weight DESC, created_at DESC
                LIMIT $2
            """, tags, limit)
            return [self._row_to_note(r) for r in rows]

    async def delete_note(self, note_id: int) -> bool:
        async with self.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM episodic_notes WHERE id = $1", note_id
            )
            return result == "DELETE 1"

    async def link_notes(self, note_id_a: int, note_id_b: int):
        async with self.acquire() as conn:
            await conn.execute("""
                UPDATE episodic_notes
                SET linked_note_ids = array_append(linked_note_ids, $2)
                WHERE id = $1 AND NOT ($2 = ANY(linked_note_ids))
            """, note_id_a, note_id_b)
            await conn.execute("""
                UPDATE episodic_notes
                SET linked_note_ids = array_append(linked_note_ids, $2)
                WHERE id = $1 AND NOT ($2 = ANY(linked_note_ids))
            """, note_id_b, note_id_a)

    async def update_note_decay(self, note_id: int, decay_weight: float):
        async with self.acquire() as conn:
            await conn.execute(
                "UPDATE episodic_notes SET decay_weight = $2 WHERE id = $1",
                note_id, decay_weight,
            )

    async def delete_notes_below_weight(self, threshold: float) -> int:
        async with self.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM episodic_notes WHERE decay_weight < $1", threshold
            )
            # result is like "DELETE 3"
            return int(result.split()[-1])

    async def get_all_notes(self) -> list[EpisodicNote]:
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM episodic_notes ORDER BY created_at DESC"
            )
            return [self._row_to_note(r) for r in rows]

    def _row_to_note(self, row) -> EpisodicNote:
        return EpisodicNote(
            id=row["id"],
            content=row["content"],
            keywords=list(row["keywords"]) if row["keywords"] else [],
            tags=list(row["tags"]) if row["tags"] else [],
            context_description=row["context_description"],
            embedding=list(row["embedding"]) if row["embedding"] else None,
            linked_note_ids=list(row["linked_note_ids"]) if row["linked_note_ids"] else [],
            decay_weight=row["decay_weight"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # --- pgvector ---

    async def has_pgvector(self) -> bool:
        """Check if pgvector extension is available."""
        return getattr(self, '_has_pgvector', False)

    async def save_note_with_vector(self, note: EpisodicNote, embedding: list[float]) -> int:
        """Save note with both FLOAT8[] embedding and vector(384) embedding_vec."""
        async with self.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO episodic_notes
                    (content, keywords, tags, context_description, embedding,
                     linked_note_ids, decay_weight, embedding_vec)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector)
                RETURNING id
            """,
                note.content, note.keywords, note.tags,
                note.context_description, embedding,
                note.linked_note_ids, note.decay_weight,
                str(embedding),  # pgvector accepts string format '[0.1,0.2,...]'
            )
            return row["id"]

    async def search_by_embedding(
        self,
        embedding: list[float],
        limit: int = 5,
        tag_filter: str | None = None,
    ) -> list[tuple[EpisodicNote, float]]:
        """Search notes by embedding similarity using pgvector."""
        if not await self.has_pgvector():
            return []
        async with self.acquire() as conn:
            embedding_str = str(embedding)
            if tag_filter:
                rows = await conn.fetch("""
                    SELECT *, 1 - (embedding_vec <=> $1::vector) as score
                    FROM episodic_notes
                    WHERE $2 = ANY(tags) AND embedding_vec IS NOT NULL
                    ORDER BY embedding_vec <=> $1::vector
                    LIMIT $3
                """, embedding_str, tag_filter, limit)
            else:
                rows = await conn.fetch("""
                    SELECT *, 1 - (embedding_vec <=> $1::vector) as score
                    FROM episodic_notes
                    WHERE embedding_vec IS NOT NULL
                    ORDER BY embedding_vec <=> $1::vector
                    LIMIT $2
                """, embedding_str, limit)

            results = []
            for row in rows:
                note = EpisodicNote(
                    content=row["content"],
                    keywords=list(row["keywords"]) if row["keywords"] else [],
                    tags=list(row["tags"]) if row["tags"] else [],
                    context_description=row["context_description"] or "",
                    embedding=list(row["embedding"]) if row["embedding"] else None,
                    linked_note_ids=list(row["linked_note_ids"]) if row["linked_note_ids"] else [],
                    decay_weight=row["decay_weight"],
                    id=row["id"],
                )
                results.append((note, float(row["score"])))
            return results

    # --- Knowledge Graph ---

    async def save_entity(self, entity: KGEntity):
        async with self.acquire() as conn:
            await conn.execute("""
                INSERT INTO kg_entities (id, entity_type, name, properties, weight, created_at)
                VALUES ($1, $2, $3, $4::jsonb, $5, $6)
                ON CONFLICT (id) DO UPDATE SET
                    entity_type = EXCLUDED.entity_type,
                    name = EXCLUDED.name,
                    properties = EXCLUDED.properties,
                    weight = EXCLUDED.weight
            """, entity.id, entity.entity_type, entity.name,
                json.dumps(entity.properties), entity.weight, entity.created_at)

    async def save_relation(self, relation: KGRelation) -> int:
        async with self.acquire() as conn:
            return await conn.fetchval("""
                INSERT INTO kg_relations (source, target, relation_type, weight, properties)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                RETURNING id
            """, relation.source_id, relation.target_id,
                relation.relation_type, relation.weight,
                json.dumps(relation.properties))

    async def get_neighbors(self, entity_id: str) -> list[KGEntity]:
        async with self.acquire() as conn:
            rows = await conn.fetch("""
                SELECT e.* FROM kg_entities e
                JOIN kg_relations r ON (r.source = $1 AND r.target = e.id)
                                    OR (r.target = $1 AND r.source = e.id)
                WHERE e.id != $1
            """, entity_id)
            return [self._row_to_entity(r) for r in rows]

    async def search_entities(
        self, name_contains: str | None = None,
        entity_type: str | None = None, limit: int = 10
    ) -> list[KGEntity]:
        conditions = []
        params = []
        idx = 1

        if name_contains:
            conditions.append(f"name ILIKE ${idx}")
            params.append(f"%{name_contains}%")
            idx += 1

        if entity_type:
            conditions.append(f"entity_type = ${idx}")
            params.append(entity_type)
            idx += 1

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)

        query = f"SELECT * FROM kg_entities {where} ORDER BY weight DESC LIMIT ${idx}"
        async with self.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._row_to_entity(r) for r in rows]

    async def get_entity(self, entity_id: str) -> KGEntity | None:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM kg_entities WHERE id = $1", entity_id
            )
            return self._row_to_entity(row) if row else None

    def _row_to_entity(self, row) -> KGEntity:
        props = row["properties"]
        if isinstance(props, str):
            props = json.loads(props)
        return KGEntity(
            id=row["id"],
            entity_type=row["entity_type"],
            name=row["name"],
            properties=props if props else {},
            weight=row["weight"],
            created_at=row["created_at"],
        )

    # --- Settings ---

    async def get_setting(self, key: str) -> dict | None:
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM settings WHERE key = $1", key
            )
            if row:
                val = row["value"]
                return json.loads(val) if isinstance(val, str) else val
            return None

    async def set_setting(self, key: str, value: dict):
        async with self.acquire() as conn:
            await conn.execute("""
                INSERT INTO settings (key, value, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_at = NOW()
            """, key, json.dumps(value))

    async def get_all_settings(self) -> dict[str, dict]:
        async with self.acquire() as conn:
            rows = await conn.fetch("SELECT key, value FROM settings")
            result = {}
            for row in rows:
                val = row["value"]
                result[row["key"]] = json.loads(val) if isinstance(val, str) else val
            return result

    async def delete_setting(self, key: str) -> bool:
        async with self.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM settings WHERE key = $1", key
            )
            return result == "DELETE 1"

    # --- Conversations ---

    @staticmethod
    def _encrypt_messages(messages: list[dict]) -> str:
        """Encrypt messages JSON for storage.

        Returns encrypted string on success, or plain JSON string if
        encryption is unavailable (no master key) or fails.
        """
        messages_json = json.dumps(messages, ensure_ascii=False)
        try:
            from breadmind.config_env import encrypt_value
            return encrypt_value(messages_json)
        except Exception:
            # No master key or encryption failure → store plaintext
            return messages_json

    @staticmethod
    def _decrypt_messages(raw) -> list[dict]:
        """Decrypt messages from DB, with fallback to plaintext.

        Handles three cases:
        1. Encrypted string → decrypt then parse JSON
        2. Plain JSON string → parse directly
        3. Already-parsed list/dict (asyncpg auto-parses JSONB) → return as-is
        """
        if not isinstance(raw, str):
            # asyncpg already parsed JSONB into Python object
            return raw if isinstance(raw, list) else []

        # Try decryption first
        try:
            from breadmind.config_env import decrypt_value
            decrypted = decrypt_value(raw)
            return json.loads(decrypted)
        except Exception:
            pass

        # Fallback: plain JSON string (pre-encryption data)
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse conversation messages, returning empty list")
            return []

    async def save_conversation(self, session_id: str, user: str, channel: str,
                                title: str, messages: list[dict], created_at=None, last_active=None):
        """Upsert conversation to DB. Messages are encrypted at rest."""
        from datetime import datetime, timezone
        encrypted_messages = self._encrypt_messages(messages)
        async with self.acquire() as conn:
            await conn.execute("""
                INSERT INTO conversations (session_id, user_id, channel, title, messages, created_at, last_active)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
                ON CONFLICT (session_id) DO UPDATE SET
                    messages = EXCLUDED.messages,
                    title = EXCLUDED.title,
                    last_active = EXCLUDED.last_active
            """, session_id, user, channel, title,
                json.dumps(encrypted_messages),
                created_at or datetime.now(timezone.utc),
                last_active or datetime.now(timezone.utc))

    async def load_conversation(self, session_id: str) -> dict | None:
        """Load a conversation from DB. Messages are decrypted transparently."""
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM conversations WHERE session_id = $1", session_id)
            if not row:
                return None
            return {
                "session_id": row["session_id"],
                "user": row["user_id"],
                "channel": row["channel"],
                "title": row["title"],
                "messages": self._decrypt_messages(row["messages"]),
                "created_at": row["created_at"],
                "last_active": row["last_active"],
            }

    async def list_conversations(self, user: str = "", limit: int = 50) -> list[dict]:
        """List recent conversations."""
        async with self.acquire() as conn:
            if user:
                rows = await conn.fetch(
                    "SELECT session_id, user_id, channel, title, created_at, last_active "
                    "FROM conversations WHERE user_id = $1 ORDER BY last_active DESC LIMIT $2",
                    user, limit)
            else:
                rows = await conn.fetch(
                    "SELECT session_id, user_id, channel, title, created_at, last_active "
                    "FROM conversations ORDER BY last_active DESC LIMIT $1",
                    limit)
            return [dict(row) for row in rows]

    async def delete_conversation(self, session_id: str) -> bool:
        async with self.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM conversations WHERE session_id = $1", session_id)
            return "DELETE 1" in result
