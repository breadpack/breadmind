"""Tests for the settings_append SDUI action handler (Phase 4)."""
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


# ---------------------------------------------------------------------------
# Unknown key
# ---------------------------------------------------------------------------

async def test_settings_append_unknown_key_rejected(bus):
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {"kind": "settings_append", "key": "evil_key", "values": {"name": "x"}},
        user_id="alice",
    )
    assert result["ok"] is False
    assert "not allowed" in result["error"].lower()
    assert store.data == {}


async def test_settings_append_phase1_key_rejected(bus):
    """Phase 1 scalar/dict keys must not be accepted by settings_append."""
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {"kind": "settings_append", "key": "llm", "values": {"default_provider": "gemini"}},
        user_id="alice",
    )
    assert result["ok"] is False
    assert "not allowed" in result["error"].lower()


# ---------------------------------------------------------------------------
# No store configured
# ---------------------------------------------------------------------------

async def test_settings_append_no_store_fails(bus):
    handler = ActionHandler(bus=bus)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "mcp_servers",
            "values": {"name": "myserver", "command": "npx"},
        },
        user_id="alice",
    )
    assert result["ok"] is False
    assert "settings_store" in result["error"].lower()


# ---------------------------------------------------------------------------
# mcp_servers
# ---------------------------------------------------------------------------

async def test_settings_append_mcp_servers_first_item(bus):
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "mcp_servers",
            "values": {"name": "k8s-mcp", "command": "npx", "args": ["-y", "k8s-mcp"]},
        },
        user_id="alice",
    )
    assert result["ok"] is True
    assert result["persisted"] is True
    assert result["refresh_view"] == "settings_view"
    servers = store.data["mcp_servers"]
    assert len(servers) == 1
    assert servers[0]["name"] == "k8s-mcp"
    assert servers[0]["command"] == "npx"


async def test_settings_append_mcp_servers_appends_to_existing(bus):
    store = FakeStore(
        {"mcp_servers": [{"name": "existing", "command": "node", "args": [], "env": {}, "enabled": True}]}
    )
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "mcp_servers",
            "values": {"name": "new-server", "command": "python"},
        },
        user_id="alice",
    )
    assert result["ok"] is True
    servers = store.data["mcp_servers"]
    assert len(servers) == 2
    assert servers[0]["name"] == "existing"
    assert servers[1]["name"] == "new-server"


async def test_settings_append_mcp_servers_duplicate_name_rejected(bus):
    store = FakeStore(
        {"mcp_servers": [{"name": "dup", "command": "node", "args": [], "env": {}, "enabled": True}]}
    )
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "mcp_servers",
            "values": {"name": "dup", "command": "python"},
        },
        user_id="alice",
    )
    assert result["ok"] is False
    assert "dup" in result["error"]
    # existing list must be unchanged
    assert len(store.data["mcp_servers"]) == 1


async def test_settings_append_mcp_servers_missing_command_rejected(bus):
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {"kind": "settings_append", "key": "mcp_servers", "values": {"name": "no-cmd"}},
        user_id="alice",
    )
    assert result["ok"] is False
    assert "command" in result["error"].lower()


async def test_settings_append_mcp_servers_args_multiline_string(bus):
    """Multiline string for args is parsed into list[str]."""
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "mcp_servers",
            "values": {
                "name": "multiline-srv",
                "command": "npx",
                "args": "-y\n  k8s-mcp  \n\n--port\n8080",
                "env": "",
                "enabled": "true",
            },
        },
        user_id="alice",
    )
    assert result["ok"] is True
    servers = store.data["mcp_servers"]
    assert servers[0]["args"] == ["-y", "k8s-mcp", "--port", "8080"]


async def test_settings_append_mcp_servers_env_multiline_string(bus):
    """Multiline string for env is parsed into dict[str, str]."""
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "mcp_servers",
            "values": {
                "name": "env-srv",
                "command": "node",
                "args": "",
                "env": "KEY1=val1\nKEY2=val2\nKEY3=has=equals",
                "enabled": "true",
            },
        },
        user_id="alice",
    )
    assert result["ok"] is True
    servers = store.data["mcp_servers"]
    assert servers[0]["env"] == {"KEY1": "val1", "KEY2": "val2", "KEY3": "has=equals"}


async def test_settings_append_mcp_servers_empty_args_env_strings(bus):
    """Empty string for args/env produces empty list/dict."""
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "mcp_servers",
            "values": {
                "name": "empty-srv",
                "command": "node",
                "args": "",
                "env": "",
                "enabled": "true",
            },
        },
        user_id="alice",
    )
    assert result["ok"] is True
    servers = store.data["mcp_servers"]
    assert servers[0]["args"] == []
    assert servers[0]["env"] == {}


async def test_settings_append_mcp_servers_invalid_env_line_rejected(bus):
    """Env string with a line missing '=' is rejected."""
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "mcp_servers",
            "values": {
                "name": "bad-env",
                "command": "node",
                "args": "",
                "env": "MISSING_EQUALS",
                "enabled": "true",
            },
        },
        user_id="alice",
    )
    assert result["ok"] is False
    assert "=" in result["error"] or "env" in result["error"].lower()


# ---------------------------------------------------------------------------
# skill_markets
# ---------------------------------------------------------------------------

async def test_settings_append_skill_markets_first_item(bus):
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "skill_markets",
            "values": {"name": "hub1", "type": "clawhub"},
        },
        user_id="alice",
    )
    assert result["ok"] is True
    markets = store.data["skill_markets"]
    assert len(markets) == 1
    assert markets[0]["name"] == "hub1"


async def test_settings_append_skill_markets_duplicate_rejected(bus):
    store = FakeStore(
        {"skill_markets": [{"name": "hub1", "type": "clawhub", "enabled": True}]}
    )
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "skill_markets",
            "values": {"name": "hub1", "type": "skills_sh"},
        },
        user_id="alice",
    )
    assert result["ok"] is False
    assert "hub1" in result["error"]


async def test_settings_append_skill_markets_invalid_type_rejected(bus):
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "skill_markets",
            "values": {"name": "hub1", "type": "unknown_type"},
        },
        user_id="alice",
    )
    assert result["ok"] is False
    assert "type" in result["error"].lower()


# ---------------------------------------------------------------------------
# safety_approval
# ---------------------------------------------------------------------------

async def test_settings_append_safety_approval_first_item(bus):
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {"kind": "settings_append", "key": "safety_approval", "values": {"tool": "k8s_delete"}},
        user_id="alice",
    )
    assert result["ok"] is True
    approval = store.data["safety_approval"]
    assert approval == ["k8s_delete"]


async def test_settings_append_safety_approval_appends(bus):
    store = FakeStore({
        "safety_approval": ["kubectl_exec"],
        "safety_permissions": {"admin_users": ["alice"]},
    })
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {"kind": "settings_append", "key": "safety_approval", "values": {"tool": "rm_rf"}},
        user_id="alice",
    )
    assert result["ok"] is True
    assert store.data["safety_approval"] == ["kubectl_exec", "rm_rf"]


async def test_settings_append_safety_approval_duplicate_rejected(bus):
    store = FakeStore({
        "safety_approval": ["kubectl_exec"],
        "safety_permissions": {"admin_users": ["alice"]},
    })
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {"kind": "settings_append", "key": "safety_approval", "values": {"tool": "kubectl_exec"}},
        user_id="alice",
    )
    assert result["ok"] is False
    assert "kubectl_exec" in result["error"]


async def test_settings_append_safety_approval_missing_tool_rejected(bus):
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {"kind": "settings_append", "key": "safety_approval", "values": {"tool": ""}},
        user_id="alice",
    )
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# safety_blacklist
# ---------------------------------------------------------------------------

async def test_settings_append_safety_blacklist_new_domain(bus):
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "safety_blacklist",
            "values": {"domain": "k8s", "tool": "pods_delete"},
        },
        user_id="alice",
    )
    assert result["ok"] is True
    bl = store.data["safety_blacklist"]
    assert bl == {"k8s": ["pods_delete"]}


async def test_settings_append_safety_blacklist_existing_domain(bus):
    store = FakeStore({
        "safety_blacklist": {"k8s": ["nodes_delete"]},
        "safety_permissions": {"admin_users": ["alice"]},
    })
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "safety_blacklist",
            "values": {"domain": "k8s", "tool": "pods_delete"},
        },
        user_id="alice",
    )
    assert result["ok"] is True
    assert store.data["safety_blacklist"] == {"k8s": ["nodes_delete", "pods_delete"]}


async def test_settings_append_safety_blacklist_duplicate_tool_rejected(bus):
    store = FakeStore({
        "safety_blacklist": {"k8s": ["pods_delete"]},
        "safety_permissions": {"admin_users": ["alice"]},
    })
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "safety_blacklist",
            "values": {"domain": "k8s", "tool": "pods_delete"},
        },
        user_id="alice",
    )
    assert result["ok"] is False
    assert "pods_delete" in result["error"]


async def test_settings_append_safety_blacklist_missing_fields_rejected(bus):
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {"kind": "settings_append", "key": "safety_blacklist", "values": {"domain": "k8s"}},
        user_id="alice",
    )
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# safety_permissions_admin_users
# ---------------------------------------------------------------------------

async def test_settings_append_admin_users_creates_list(bus):
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "safety_permissions_admin_users",
            "values": {"user": "alice"},
        },
        user_id="alice",
    )
    assert result["ok"] is True
    perms = store.data["safety_permissions"]
    assert perms["admin_users"] == ["alice"]


async def test_settings_append_admin_users_appends(bus):
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "safety_permissions_admin_users",
            "values": {"user": "bob"},
        },
        user_id="alice",
    )
    assert result["ok"] is True
    perms = store.data["safety_permissions"]
    assert perms["admin_users"] == ["alice", "bob"]


async def test_settings_append_admin_users_preserves_user_permissions(bus):
    """Appending an admin_user must not overwrite existing user_permissions."""
    store = FakeStore({
        "safety_permissions": {
            "admin_users": ["alice"],
            "user_permissions": {"charlie": ["tool_a"]},
        }
    })
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "safety_permissions_admin_users",
            "values": {"user": "bob"},
        },
        user_id="alice",
    )
    assert result["ok"] is True
    perms = store.data["safety_permissions"]
    assert perms["admin_users"] == ["alice", "bob"]
    assert perms["user_permissions"] == {"charlie": ["tool_a"]}


async def test_settings_append_admin_users_duplicate_rejected(bus):
    store = FakeStore({"safety_permissions": {"admin_users": ["alice"]}})
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "safety_permissions_admin_users",
            "values": {"user": "alice"},
        },
        user_id="alice",
    )
    assert result["ok"] is False
    assert "alice" in result["error"]


async def test_settings_append_admin_users_missing_user_rejected(bus):
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "safety_permissions_admin_users",
            "values": {"user": ""},
        },
        user_id="alice",
    )
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# scheduler_cron
# ---------------------------------------------------------------------------

async def test_settings_append_scheduler_cron_first_item(bus):
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "scheduler_cron",
            "values": {"name": "daily-backup", "schedule": "0 2 * * *", "task": "run backup"},
        },
        user_id="alice",
    )
    assert result["ok"] is True
    jobs = store.data["scheduler_cron"]
    assert len(jobs) == 1
    assert jobs[0]["name"] == "daily-backup"
    assert "id" in jobs[0]


async def test_settings_append_scheduler_cron_appends(bus):
    store = FakeStore({
        "scheduler_cron": [
            {"id": "abc", "name": "first-job", "schedule": "0 * * * *", "task": "ping", "enabled": True}
        ]
    })
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "scheduler_cron",
            "values": {"name": "second-job", "schedule": "0 1 * * *", "task": "backup"},
        },
        user_id="alice",
    )
    assert result["ok"] is True
    jobs = store.data["scheduler_cron"]
    assert len(jobs) == 2
    assert jobs[1]["name"] == "second-job"


async def test_settings_append_scheduler_cron_duplicate_name_rejected(bus):
    store = FakeStore({
        "scheduler_cron": [
            {"id": "abc", "name": "daily", "schedule": "0 2 * * *", "task": "run", "enabled": True}
        ]
    })
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "scheduler_cron",
            "values": {"name": "daily", "schedule": "0 3 * * *", "task": "other"},
        },
        user_id="alice",
    )
    assert result["ok"] is False
    assert "daily" in result["error"]


async def test_settings_append_scheduler_cron_missing_schedule_rejected(bus):
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "scheduler_cron",
            "values": {"name": "no-schedule", "task": "run"},
        },
        user_id="alice",
    )
    assert result["ok"] is False
    assert "schedule" in result["error"].lower()
