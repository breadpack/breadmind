"""Tests for the dynamic RoleRegistry with DB persistence."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock


from breadmind.core.role_registry import RoleDefinition, RoleRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_role(
    name: str = "test_role",
    *,
    domain: str = "general",
    task_type: str = "analyst",
    tools: list[str] | None = None,
    tool_mode: str = "whitelist",
    persistent: bool = True,
    created_by: str = "user",
    provider: str = "",
    model: str = "",
    description: str = "",
) -> RoleDefinition:
    return RoleDefinition(
        name=name,
        domain=domain,
        task_type=task_type,
        system_prompt=f"You are a {name}.",
        description=description or f"Test role: {name}",
        provider=provider,
        model=model,
        tool_mode=tool_mode,
        tools=tools or [],
        persistent=persistent,
        created_by=created_by,
    )


def make_mock_db(rows=None):
    """Return a (db, conn) pair; conn is an AsyncMock with fetch/execute."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows or [])
    conn.execute = AsyncMock()

    @asynccontextmanager
    async def _acquire():
        yield conn

    db = MagicMock()
    db.acquire = _acquire
    return db, conn


# ---------------------------------------------------------------------------
# Basic state
# ---------------------------------------------------------------------------

def test_registry_starts_empty():
    reg = RoleRegistry()
    assert reg.list_roles() == []


async def test_register_and_get():
    reg = RoleRegistry()
    role = make_role("alpha")
    await reg.register(role)

    result = reg.get("alpha")
    assert result is role


async def test_get_nonexistent_returns_none():
    reg = RoleRegistry()
    assert reg.get("nope") is None


# ---------------------------------------------------------------------------
# DB persistence — register
# ---------------------------------------------------------------------------

async def test_register_persistent_saves_to_db():
    reg = RoleRegistry()
    role = make_role("k8s_diag", persistent=True)
    db, conn = make_mock_db()

    await reg.register(role, db=db)

    conn.execute.assert_awaited_once()
    sql: str = conn.execute.call_args[0][0]
    assert "INSERT INTO subagent_roles" in sql
    assert "ON CONFLICT (name) DO UPDATE" in sql


async def test_register_transient_skips_db():
    reg = RoleRegistry()
    role = make_role("temp_role", persistent=False)
    db, conn = make_mock_db()

    await reg.register(role, db=db)

    conn.execute.assert_not_awaited()
    assert reg.get("temp_role") is not None


async def test_register_persistent_no_db_stays_in_memory():
    reg = RoleRegistry()
    role = make_role("mem_only", persistent=True)
    await reg.register(role)  # no db arg — must not raise
    assert reg.get("mem_only") is role


# ---------------------------------------------------------------------------
# DB persistence — load_from_db
# ---------------------------------------------------------------------------

async def test_load_from_db():
    reg = RoleRegistry()
    rows = [
        {
            "name": "loaded_role",
            "domain": "k8s",
            "task_type": "diagnostician",
            "system_prompt": "You diagnose.",
            "description": "Loaded from DB",
            "provider": "anthropic",
            "model": "claude-3-5-haiku-20241022",
            "tool_mode": "whitelist",
            "tools": json.dumps(["pods_list", "events_list"]),
            "persistent": True,
            "created_by": "user",
            "max_turns": 5,
        }
    ]
    db, _ = make_mock_db(rows=rows)

    count = await reg.load_from_db(db)

    assert count == 1
    role = reg.get("loaded_role")
    assert role is not None
    assert role.domain == "k8s"
    assert role.tools == ["pods_list", "events_list"]
    assert role.provider == "anthropic"


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------

async def test_remove_existing_role():
    reg = RoleRegistry()
    await reg.register(make_role("to_remove"))
    assert await reg.remove("to_remove") is True
    assert reg.get("to_remove") is None


async def test_remove_nonexistent_returns_false():
    reg = RoleRegistry()
    assert await reg.remove("ghost_role") is False


async def test_remove_persistent_deletes_from_db():
    reg = RoleRegistry()
    db, conn = make_mock_db()
    await reg.register(make_role("db_role", persistent=True), db=db)

    conn.execute.reset_mock()
    await reg.remove("db_role", db=db)

    conn.execute.assert_awaited_once()
    sql: str = conn.execute.call_args[0][0]
    assert "DELETE FROM subagent_roles" in sql


async def test_remove_transient_skips_db_delete():
    reg = RoleRegistry()
    db, conn = make_mock_db()
    await reg.register(make_role("transient", persistent=False), db=db)

    conn.execute.reset_mock()
    await reg.remove("transient", db=db)

    conn.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# get_tools
# ---------------------------------------------------------------------------

async def test_get_tools_whitelist_mode():
    reg = RoleRegistry()
    await reg.register(make_role("tooled", tools=["shell_exec", "file_read"], tool_mode="whitelist"))

    mode, tools = reg.get_tools("tooled")
    assert mode == "whitelist"
    assert tools == ["shell_exec", "file_read"]


async def test_get_tools_unknown_role_returns_default():
    reg = RoleRegistry()
    mode, tools = reg.get_tools("unknown")
    assert mode == "whitelist"
    assert tools == []


async def test_get_tools_blacklist_mode():
    reg = RoleRegistry()
    await reg.register(make_role("restricted", tools=["dangerous_tool"], tool_mode="blacklist"))

    mode, tools = reg.get_tools("restricted")
    assert mode == "blacklist"
    assert "dangerous_tool" in tools


# ---------------------------------------------------------------------------
# get_model_config
# ---------------------------------------------------------------------------

async def test_get_model_config_known_role():
    reg = RoleRegistry()
    await reg.register(make_role("smart_role", provider="anthropic", model="claude-opus-4-5"))

    provider, model = reg.get_model_config("smart_role")
    assert provider == "anthropic"
    assert model == "claude-opus-4-5"


async def test_get_model_config_unknown_role():
    reg = RoleRegistry()
    provider, model = reg.get_model_config("nobody")
    assert provider == ""
    assert model == ""


# ---------------------------------------------------------------------------
# cleanup_transient
# ---------------------------------------------------------------------------

async def test_cleanup_transient_removes_only_non_persistent():
    reg = RoleRegistry()
    await reg.register(make_role("perm1", persistent=True))
    await reg.register(make_role("perm2", persistent=True))
    await reg.register(make_role("temp1", persistent=False))
    await reg.register(make_role("temp2", persistent=False))

    removed = reg.cleanup_transient()

    assert set(removed) == {"temp1", "temp2"}
    assert reg.get("perm1") is not None
    assert reg.get("perm2") is not None
    assert reg.get("temp1") is None
    assert reg.get("temp2") is None


def test_cleanup_transient_empty_registry():
    reg = RoleRegistry()
    assert reg.cleanup_transient() == []


# ---------------------------------------------------------------------------
# list_role_summaries
# ---------------------------------------------------------------------------

def test_list_role_summaries_empty():
    reg = RoleRegistry()
    summary = reg.list_role_summaries()
    assert "No subagent roles defined" in summary
    assert "spawn_agent" in summary


async def test_list_role_summaries_contains_role_info():
    reg = RoleRegistry()
    role = make_role(
        "k8s_diag",
        domain="k8s",
        task_type="diagnostician",
        tools=["pods_list", "events_list"],
        description="Diagnoses k8s issues",
    )
    await reg.register(role)

    summary = reg.list_role_summaries()
    assert "k8s_diag" in summary
    assert "k8s/diagnostician" in summary
    assert "Diagnoses k8s issues" in summary
    assert "pods_list" in summary


async def test_list_role_summaries_tool_preview_truncated():
    reg = RoleRegistry()
    tools = [f"tool_{i}" for i in range(10)]
    await reg.register(make_role("big_role", tools=tools))

    summary = reg.list_role_summaries()
    assert "+5 more" in summary


# ---------------------------------------------------------------------------
# RoleDefinition serialisation
# ---------------------------------------------------------------------------

def test_role_definition_to_dict_round_trip():
    role = make_role("serialised", tools=["a", "b"], provider="gemini", model="gemini-2-flash")
    restored = RoleDefinition.from_dict(role.to_dict())

    assert restored.name == role.name
    assert restored.tools == role.tools
    assert restored.provider == role.provider
    assert restored.model == role.model


def test_role_definition_from_dict_tools_as_json_string():
    data = {
        "name": "json_role",
        "tools": json.dumps(["x", "y", "z"]),
    }
    role = RoleDefinition.from_dict(data)
    assert role.tools == ["x", "y", "z"]
