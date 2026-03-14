import json

import asyncpg
from contextlib import asynccontextmanager

from breadmind.storage.models import EpisodicNote, KGEntity, KGRelation


class Database:
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

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
            """)

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
