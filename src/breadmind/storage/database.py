import asyncpg
from contextlib import asynccontextmanager


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
                    embedding vector(384),
                    linked_note_ids INTEGER[] DEFAULT '{}',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
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
