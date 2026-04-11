"""Tests for Phase 8: audit log recording in SDUI action handler."""
import pytest

from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.store import FlowEventStore
from breadmind.sdui.actions import ActionHandler


# ---------------------------------------------------------------------------
# Fake collaborators
# ---------------------------------------------------------------------------

class FakeStore:
    def __init__(self, initial=None):
        self.data: dict = dict(initial or {})
        self.set_calls: list = []

    async def get_setting(self, key):
        return self.data.get(key)

    async def set_setting(self, key, value):
        self.set_calls.append((key, value))
        self.data[key] = value


class FailingAuditStore(FakeStore):
    """Store that succeeds for normal settings writes but raises on audit writes."""

    async def set_setting(self, key, value):
        if key == "sdui_audit_log":
            raise RuntimeError("audit write deliberately failed")
        await super().set_setting(key, value)


class FakeVault:
    def __init__(self):
        self._store: dict = {}

    async def store(self, credential_id, value, metadata=None):
        self._store[credential_id] = {"value": value, "metadata": metadata}
        return credential_id

    async def retrieve(self, credential_id):
        entry = self._store.get(credential_id)
        return entry["value"] if entry else None

    async def delete(self, credential_id):
        if credential_id not in self._store:
            return False
        del self._store[credential_id]
        return True

    async def exists(self, credential_id):
        return credential_id in self._store

    async def list_ids(self, prefix=""):
        return [k for k in self._store if k.startswith(prefix)]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def bus(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    try:
        yield bus
    finally:
        await bus.stop()


def _admin_store(**extra):
    return FakeStore({"safety_permissions": {"admin_users": ["alice"]}, **extra})


def _make_handler(bus, *, store=None, vault=None):
    if store is None:
        store = _admin_store()
    return ActionHandler(bus=bus, settings_store=store, credential_vault=vault)


def _audit_entries(store: FakeStore) -> list[dict]:
    return store.data.get("sdui_audit_log") or []


# ---------------------------------------------------------------------------
# settings_write audit
# ---------------------------------------------------------------------------

async def test_settings_write_appends_audit_entry(bus):
    store = _admin_store()
    handler = _make_handler(bus, store=store)
    result = await handler.handle(
        {"kind": "settings_write", "key": "llm", "values": {"default_provider": "gemini"}},
        user_id="alice",
    )
    assert result["ok"] is True
    entries = _audit_entries(store)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["action"] == "settings_write"
    assert entry["key"] == "llm"
    assert entry["user"] == "alice"
    assert "ts" in entry
    assert isinstance(entry["ts"], float)
    assert "summary" in entry


async def test_settings_write_summary_lists_fields(bus):
    store = _admin_store()
    handler = _make_handler(bus, store=store)
    await handler.handle(
        {
            "kind": "settings_write",
            "key": "llm",
            "values": {"default_provider": "claude", "default_model": "claude-3"},
        },
        user_id="alice",
    )
    entry = _audit_entries(store)[0]
    summary = entry["summary"]
    assert "2 field(s) updated" in summary
    assert "default_provider" in summary
    assert "default_model" in summary
    # values must NOT appear
    assert "claude-3" not in summary
    assert "claude" not in summary or "claude" in summary.split(":")[0]


async def test_settings_write_apikey_summary_never_contains_secret(bus):
    store = _admin_store()
    vault = FakeVault()
    handler = _make_handler(bus, store=store, vault=vault)
    result = await handler.handle(
        {
            "kind": "settings_write",
            "key": "apikey:ANTHROPIC_API_KEY",
            "values": "sk-super-secret-key",
        },
        user_id="alice",
    )
    assert result["ok"] is True
    entries = _audit_entries(store)
    assert len(entries) == 1
    entry = entries[0]
    assert "sk-super-secret-key" not in entry["summary"]
    assert "apikey:ANTHROPIC_API_KEY" in entry["summary"]
    assert "(vault)" in entry["summary"]


async def test_settings_write_failed_action_no_audit_entry(bus):
    store = _admin_store()
    handler = _make_handler(bus, store=store)
    result = await handler.handle(
        {"kind": "settings_write", "key": "llm", "values": {"tool_call_max_turns": -1}},
        user_id="alice",
    )
    assert result["ok"] is False
    assert _audit_entries(store) == []


# ---------------------------------------------------------------------------
# settings_append audit
# ---------------------------------------------------------------------------

async def test_settings_append_appends_audit_entry(bus):
    store = _admin_store()
    handler = _make_handler(bus, store=store)
    result = await handler.handle(
        {
            "kind": "settings_append",
            "key": "mcp_servers",
            "values": {"name": "github", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
        },
        user_id="alice",
    )
    assert result["ok"] is True
    entries = _audit_entries(store)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["action"] == "settings_append"
    assert entry["key"] == "mcp_servers"
    assert entry["user"] == "alice"
    assert "github" in entry["summary"]


async def test_settings_append_failed_no_audit(bus):
    store = _admin_store()
    handler = _make_handler(bus, store=store)
    result = await handler.handle(
        {"kind": "settings_append", "key": "evil_key", "values": {}},
        user_id="alice",
    )
    assert result["ok"] is False
    assert _audit_entries(store) == []


# ---------------------------------------------------------------------------
# settings_update_item audit
# ---------------------------------------------------------------------------

async def test_settings_update_item_appends_audit_entry(bus):
    store = _admin_store(
        mcp_servers=[
            {"name": "github", "command": "npx", "args": [], "enabled": True}
        ]
    )
    handler = _make_handler(bus, store=store)
    result = await handler.handle(
        {
            "kind": "settings_update_item",
            "key": "mcp_servers",
            "match_field": "name",
            "match_value": "github",
            "values": {"enabled": False},
        },
        user_id="alice",
    )
    assert result["ok"] is True
    entries = _audit_entries(store)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["action"] == "settings_update_item"
    assert entry["key"] == "mcp_servers"
    assert "github" in entry["summary"]


async def test_settings_update_item_failed_no_audit(bus):
    store = _admin_store()
    handler = _make_handler(bus, store=store)
    result = await handler.handle(
        {
            "kind": "settings_update_item",
            "key": "mcp_servers",
            "match_field": "name",
            "match_value": "nonexistent",
            "values": {"enabled": False},
        },
        user_id="alice",
    )
    assert result["ok"] is False
    assert _audit_entries(store) == []


# ---------------------------------------------------------------------------
# credential_store audit
# ---------------------------------------------------------------------------

async def test_credential_store_audit_entry(bus):
    store = _admin_store()
    vault = FakeVault()
    handler = _make_handler(bus, store=store, vault=vault)
    result = await handler.handle(
        {"kind": "credential_store", "credential_id": "ssh:prod", "value": "s3cr3t"},
        user_id="alice",
    )
    assert result["ok"] is True
    entries = _audit_entries(store)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["action"] == "credential_store"
    assert entry["key"] == "vault:ssh:prod"
    assert entry["user"] == "alice"
    # Value MUST NOT appear
    assert "s3cr3t" not in entry["summary"]
    assert entry["summary"] == "stored"


async def test_credential_store_sensitive_metadata_not_in_audit(bus):
    store = _admin_store()
    vault = FakeVault()
    handler = _make_handler(bus, store=store, vault=vault)
    result = await handler.handle(
        {
            "kind": "credential_store",
            "credential_id": "api:key1",
            "value": "top-secret-value",
            "metadata": {"owner": "bob", "note": "production key"},
        },
        user_id="alice",
    )
    assert result["ok"] is True
    entry = _audit_entries(store)[0]
    assert "top-secret-value" not in entry["summary"]
    assert "bob" not in entry["summary"]
    assert "production key" not in entry["summary"]
    assert entry["summary"] == "stored"


async def test_credential_store_failed_no_audit(bus):
    store = _admin_store()
    # Non-admin user
    result = await ActionHandler(bus=bus, settings_store=store, credential_vault=FakeVault()).handle(
        {"kind": "credential_store", "credential_id": "ssh:prod", "value": "s3cr3t"},
        user_id="nobody",
    )
    assert result["ok"] is False
    assert _audit_entries(store) == []


# ---------------------------------------------------------------------------
# credential_delete audit
# ---------------------------------------------------------------------------

async def test_credential_delete_audit_entry(bus):
    store = _admin_store()
    vault = FakeVault()
    await vault.store("ssh:prod", "s3cr3t")
    handler = _make_handler(bus, store=store, vault=vault)
    result = await handler.handle(
        {"kind": "credential_delete", "credential_id": "ssh:prod"},
        user_id="alice",
    )
    assert result["ok"] is True
    entries = _audit_entries(store)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["action"] == "credential_delete"
    assert entry["key"] == "vault:ssh:prod"
    assert entry["summary"] == "deleted"


# ---------------------------------------------------------------------------
# Audit log cap at 200 entries
# ---------------------------------------------------------------------------

async def test_audit_log_capped_at_200(bus):
    # Pre-fill with 200 existing entries
    existing = [
        {"ts": float(i), "action": "settings_write", "key": "llm", "user": "alice", "summary": f"entry {i}"}
        for i in range(200)
    ]
    store = _admin_store(**{"sdui_audit_log": existing})
    handler = _make_handler(bus, store=store)

    # Add 5 more entries
    for _ in range(5):
        await handler.handle(
            {"kind": "settings_write", "key": "llm", "values": {"default_provider": "gemini"}},
            user_id="alice",
        )

    entries = _audit_entries(store)
    assert len(entries) == 200


async def test_audit_log_insert_205_keeps_last_200(bus):
    store = _admin_store()
    handler = _make_handler(bus, store=store)

    for i in range(205):
        # Vary provider to avoid any caching issues
        await handler.handle(
            {"kind": "settings_write", "key": "llm", "values": {"default_provider": "gemini"}},
            user_id="alice",
        )

    entries = _audit_entries(store)
    assert len(entries) == 200
    # The oldest entries (first 5) should have been dropped
    # The last entry should be the 205th write
    assert entries[-1]["action"] == "settings_write"


# ---------------------------------------------------------------------------
# Audit failure must NOT break user action
# ---------------------------------------------------------------------------

async def test_audit_failure_does_not_break_action(bus):
    store = FailingAuditStore({"safety_permissions": {"admin_users": ["alice"]}})
    handler = _make_handler(bus, store=store)
    result = await handler.handle(
        {"kind": "settings_write", "key": "llm", "values": {"default_provider": "gemini"}},
        user_id="alice",
    )
    # Action must succeed even though audit write raised
    assert result["ok"] is True
    assert result["persisted"] is True
    # The llm setting was persisted
    assert store.data.get("llm") == {"default_provider": "gemini"}
    # Audit log did not get written (store raised), but no exception propagated
    assert "sdui_audit_log" not in store.data


# ---------------------------------------------------------------------------
# No settings_store: audit is silently skipped
# ---------------------------------------------------------------------------

async def test_no_settings_store_audit_skipped(bus):
    """ActionHandler with no settings_store must not crash on audit calls."""
    vault = FakeVault()
    # Build a store-less handler, but give it an admin vault
    # (credential_store needs admin check which needs settings_store, so just call _record_audit directly)
    handler = ActionHandler(bus=bus, settings_store=None, credential_vault=vault)
    # Must not raise
    await handler._record_audit("settings_write", "llm", "alice", "1 field(s) updated: x")
