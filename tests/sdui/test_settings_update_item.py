"""Tests for the settings_update_item SDUI action handler (Phase 6)."""
import pytest

from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.store import FlowEventStore
from breadmind.sdui.actions import ActionHandler


class FakeStore:
    def __init__(self, initial=None):
        self.data: dict = dict(initial or {})

    async def get_setting(self, key):
        return self.data.get(key)

    async def set_setting(self, key, value):
        self.data[key] = value


@pytest.fixture
async def bus(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    try:
        yield bus
    finally:
        await bus.stop()


_EXISTING_SERVERS = [
    {"name": "github", "command": "npx", "args": ["-y", "github-mcp"], "env": {"TOKEN": "abc"}, "enabled": True},
    {"name": "brave", "command": "npx", "args": ["-y", "brave-mcp"], "env": {}, "enabled": False},
]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

async def test_update_item_mcp_servers_command(bus):
    """Update the command of an existing mcp_servers entry."""
    store = FakeStore({"mcp_servers": list(_EXISTING_SERVERS)})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_update_item",
            "key": "mcp_servers",
            "match_field": "name",
            "match_value": "github",
            "values": {
                "name": "github",
                "command": "node",
                "args": "-y\ngithub-mcp",
                "env": "TOKEN=xyz",
                "enabled": "true",
            },
        },
        user_id="alice",
    )
    assert result["ok"] is True
    assert result["persisted"] is True
    assert result["refresh_view"] == "settings_view"
    servers = store.data["mcp_servers"]
    github = next(s for s in servers if s["name"] == "github")
    assert github["command"] == "node"
    assert github["args"] == ["-y", "github-mcp"]
    assert github["env"] == {"TOKEN": "xyz"}
    assert github["enabled"] is True


async def test_update_item_preserves_other_items(bus):
    """Updating one item must not modify other items in the list."""
    store = FakeStore({"mcp_servers": list(_EXISTING_SERVERS)})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_update_item",
            "key": "mcp_servers",
            "match_field": "name",
            "match_value": "github",
            "values": {
                "name": "github",
                "command": "updated-cmd",
                "args": "",
                "env": "",
                "enabled": "true",
            },
        },
        user_id="alice",
    )
    assert result["ok"] is True
    servers = store.data["mcp_servers"]
    brave = next(s for s in servers if s["name"] == "brave")
    assert brave["command"] == "npx"
    assert brave["args"] == ["-y", "brave-mcp"]
    assert brave["enabled"] is False


# ---------------------------------------------------------------------------
# args/env multiline parsing
# ---------------------------------------------------------------------------

async def test_update_item_args_multiline_parsed(bus):
    """Multiline args string is parsed into list[str]."""
    store = FakeStore({"mcp_servers": list(_EXISTING_SERVERS)})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_update_item",
            "key": "mcp_servers",
            "match_field": "name",
            "match_value": "github",
            "values": {
                "name": "github",
                "command": "npx",
                "args": "-y\n  github-mcp  \n  \n--port\n8080",
                "env": "",
                "enabled": "true",
            },
        },
        user_id="alice",
    )
    assert result["ok"] is True
    servers = store.data["mcp_servers"]
    github = next(s for s in servers if s["name"] == "github")
    assert github["args"] == ["-y", "github-mcp", "--port", "8080"]


async def test_update_item_env_multiline_parsed(bus):
    """Multiline env string is parsed into dict[str, str]."""
    store = FakeStore({"mcp_servers": list(_EXISTING_SERVERS)})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_update_item",
            "key": "mcp_servers",
            "match_field": "name",
            "match_value": "github",
            "values": {
                "name": "github",
                "command": "npx",
                "args": "",
                "env": "KEY1=val1\n  \nKEY2=val2\nKEY3=has=equals",
                "enabled": "true",
            },
        },
        user_id="alice",
    )
    assert result["ok"] is True
    servers = store.data["mcp_servers"]
    github = next(s for s in servers if s["name"] == "github")
    assert github["env"] == {"KEY1": "val1", "KEY2": "val2", "KEY3": "has=equals"}


async def test_update_item_empty_args_env(bus):
    """Empty args/env strings produce empty list/dict."""
    store = FakeStore({"mcp_servers": list(_EXISTING_SERVERS)})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_update_item",
            "key": "mcp_servers",
            "match_field": "name",
            "match_value": "github",
            "values": {
                "name": "github",
                "command": "npx",
                "args": "",
                "env": "",
                "enabled": "true",
            },
        },
        user_id="alice",
    )
    assert result["ok"] is True
    servers = store.data["mcp_servers"]
    github = next(s for s in servers if s["name"] == "github")
    assert github["args"] == []
    assert github["env"] == {}


async def test_update_item_invalid_env_line_rejected(bus):
    """Env line without '=' is rejected."""
    store = FakeStore({"mcp_servers": list(_EXISTING_SERVERS)})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_update_item",
            "key": "mcp_servers",
            "match_field": "name",
            "match_value": "github",
            "values": {
                "name": "github",
                "command": "npx",
                "args": "",
                "env": "INVALID_LINE_NO_EQUALS",
                "enabled": "true",
            },
        },
        user_id="alice",
    )
    assert result["ok"] is False
    assert "=" in result["error"] or "env" in result["error"].lower()


# ---------------------------------------------------------------------------
# enabled string coercion
# ---------------------------------------------------------------------------

async def test_update_item_enabled_true_string(bus):
    """enabled='true' is coerced to bool True."""
    store = FakeStore({"mcp_servers": list(_EXISTING_SERVERS)})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_update_item",
            "key": "mcp_servers",
            "match_field": "name",
            "match_value": "brave",
            "values": {
                "name": "brave",
                "command": "npx",
                "args": "",
                "env": "",
                "enabled": "true",
            },
        },
        user_id="alice",
    )
    assert result["ok"] is True
    servers = store.data["mcp_servers"]
    brave = next(s for s in servers if s["name"] == "brave")
    assert brave["enabled"] is True


async def test_update_item_enabled_false_string(bus):
    """enabled='false' is coerced to bool False."""
    store = FakeStore({"mcp_servers": list(_EXISTING_SERVERS)})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_update_item",
            "key": "mcp_servers",
            "match_field": "name",
            "match_value": "github",
            "values": {
                "name": "github",
                "command": "npx",
                "args": "",
                "env": "",
                "enabled": "false",
            },
        },
        user_id="alice",
    )
    assert result["ok"] is True
    servers = store.data["mcp_servers"]
    github = next(s for s in servers if s["name"] == "github")
    assert github["enabled"] is False


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

async def test_update_item_not_found_returns_error(bus):
    """Trying to update a nonexistent item returns an error."""
    store = FakeStore({"mcp_servers": list(_EXISTING_SERVERS)})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_update_item",
            "key": "mcp_servers",
            "match_field": "name",
            "match_value": "does-not-exist",
            "values": {
                "name": "does-not-exist",
                "command": "npx",
                "args": "",
                "env": "",
                "enabled": "true",
            },
        },
        user_id="alice",
    )
    assert result["ok"] is False
    assert "not found" in result["error"].lower() or "does-not-exist" in result["error"]


async def test_update_item_unknown_key_rejected(bus):
    """Keys not in the update_item whitelist are rejected."""
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_update_item",
            "key": "llm",
            "match_field": "name",
            "match_value": "x",
            "values": {"name": "x"},
        },
        user_id="alice",
    )
    assert result["ok"] is False
    assert "not allowed" in result["error"].lower()


async def test_update_item_vault_key_rejected(bus):
    """Credential/vault keys are not in the whitelist."""
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_update_item",
            "key": "apikey:ANTHROPIC_API_KEY",
            "match_field": "name",
            "match_value": "x",
            "values": {"name": "x"},
        },
        user_id="alice",
    )
    assert result["ok"] is False
    assert "not allowed" in result["error"].lower()


async def test_update_item_no_store_fails(bus):
    """Returns error when settings_store is not configured."""
    handler = ActionHandler(bus=bus)
    result = await handler.handle(
        {
            "kind": "settings_update_item",
            "key": "mcp_servers",
            "match_field": "name",
            "match_value": "github",
            "values": {
                "name": "github",
                "command": "npx",
                "args": "",
                "env": "",
                "enabled": "true",
            },
        },
        user_id="alice",
    )
    assert result["ok"] is False
    assert "settings_store" in result["error"].lower()
