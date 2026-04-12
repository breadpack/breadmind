import pytest

from breadmind.hooks.db_store import HookOverride, HookOverrideStore


class _FakePool:
    """Minimal fake asyncpg pool using an in-memory list."""
    def __init__(self):
        self.rows: list[dict] = []
        self._idx = 0

    def acquire(self):
        pool = self
        class _Ctx:
            async def __aenter__(self_): return _Conn(pool)
            async def __aexit__(self_, *a): return False
        return _Ctx()


class _Conn:
    def __init__(self, pool): self._pool = pool

    async def fetch(self, sql, *args):
        if "WHERE event" in sql:
            event = args[0]
            return [r for r in self._pool.rows if r["event"] == event]
        return list(self._pool.rows)

    async def execute(self, sql, *args):
        if "INSERT" in sql:
            self._pool._idx += 1
            self._pool.rows.append({
                "id": f"id{self._pool._idx}",
                "hook_id": args[0],
                "source": args[1],
                "event": args[2],
                "type": args[3],
                "tool_pattern": args[4],
                "priority": args[5],
                "enabled": args[6],
                "config_json": args[7],
            })


async def test_insert_and_list():
    store = HookOverrideStore(pool=_FakePool())
    await store.insert(HookOverride(
        hook_id="block-rm",
        source="user",
        event="pre_tool_use",
        type="shell",
        tool_pattern="shell_*",
        priority=100,
        enabled=True,
        config_json={"command": "exit 1"},
    ))
    rows = await store.list_by_event("pre_tool_use")
    assert len(rows) == 1
    assert rows[0].hook_id == "block-rm"
    assert rows[0].config_json == {"command": "exit 1"}
