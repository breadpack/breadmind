import json

import pytest

from breadmind.hooks.db_store import HookOverride, HookOverrideStore


class _FakePool:
    """Fake asyncpg pool enforcing the real JSONB parameter contract.

    asyncpg rejects Python dicts as bind parameters for JSONB columns
    unless a type codec is registered — it expects a JSON *string*.
    This fake mirrors that rule so tests can catch the class of bug
    that otherwise only shows up against a real DB.
    """

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
            cfg_param = args[7]
            if not isinstance(cfg_param, str):
                raise TypeError(
                    f"invalid input for query argument $8: {cfg_param!r} "
                    f"(expected str, got {type(cfg_param).__name__})",
                )
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
                # Store as string so _row_to_override exercises its
                # json.loads branch, matching real-DB row shape.
                "config_json": cfg_param,
            })
        elif "DELETE" in sql:
            self._pool.rows = [r for r in self._pool.rows if r["hook_id"] != args[0]]


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


async def test_insert_serializes_dict_to_jsonb_string():
    """Regression: dict config_json must be JSON-serialized before the
    asyncpg bind, otherwise real asyncpg raises DataError against
    jsonb columns (caught via playwright smoke test 2026-04-12).
    """
    pool = _FakePool()
    store = HookOverrideStore(pool=pool)
    await store.insert(HookOverride(
        hook_id="dict-cfg",
        source="user",
        event="pre_tool_use",
        type="shell",
        tool_pattern=None,
        priority=0,
        enabled=True,
        config_json={"command": "echo hi", "nested": {"a": 1}},
    ))
    assert len(pool.rows) == 1
    stored = pool.rows[0]["config_json"]
    assert isinstance(stored, str), "insert must serialize dict to JSON string"
    assert json.loads(stored) == {"command": "echo hi", "nested": {"a": 1}}


async def test_insert_accepts_pre_serialized_string():
    pool = _FakePool()
    store = HookOverrideStore(pool=pool)
    await store.insert(HookOverride(
        hook_id="str-cfg",
        source="user",
        event="pre_tool_use",
        type="shell",
        tool_pattern=None,
        priority=0,
        enabled=True,
        config_json='{"command":"echo"}',  # already a string
    ))
    assert pool.rows[0]["config_json"] == '{"command":"echo"}'
