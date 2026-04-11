import pytest

from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.store import FlowEventStore
from breadmind.sdui.actions import ActionHandler


class FakeStore:
    def __init__(self):
        self.data: dict = {}

    async def get_setting(self, key):
        return self.data.get(key)

    async def set_setting(self, key, value):
        self.data[key] = value


class FakeVault:
    def __init__(self):
        self.calls: list = []

    async def store(self, credential_id, value, metadata=None):
        self.calls.append((credential_id, value, metadata))
        return credential_id

    async def retrieve(self, credential_id):
        for cid, value, _ in self.calls:
            if cid == credential_id:
                return value
        return None


@pytest.fixture
async def bus(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    try:
        yield bus
    finally:
        await bus.stop()


async def test_settings_write_persists_llm(bus):
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_write",
            "key": "llm",
            "values": {"default_provider": "gemini", "tool_call_max_turns": 12},
        },
        user_id="alice",
    )
    assert result["ok"] is True
    assert result["persisted"] is True
    assert result.get("restart_required") is False
    assert result["refresh_view"] == "settings_view"
    assert store.data["llm"] == {"default_provider": "gemini", "tool_call_max_turns": 12}


async def test_settings_write_rejects_unknown_key(bus):
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {"kind": "settings_write", "key": "evil_key", "values": {}},
        user_id="alice",
    )
    assert result["ok"] is False
    assert "not allowed" in result["error"].lower()
    assert store.data == {}


async def test_settings_write_validation_error(bus):
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_write",
            "key": "llm",
            "values": {"tool_call_max_turns": 999},
        },
        user_id="alice",
    )
    assert result["ok"] is False
    assert "tool_call_max_turns" in result["error"]
    assert store.data == {}


async def test_settings_write_apikey_routes_to_vault(bus):
    store = FakeStore()
    vault = FakeVault()
    handler = ActionHandler(bus=bus, settings_store=store, credential_vault=vault)
    result = await handler.handle(
        {
            "kind": "settings_write",
            "key": "apikey:GEMINI_API_KEY",
            "values": "secret-key-abc",
        },
        user_id="alice",
    )
    assert result["ok"] is True
    assert result["persisted"] is True
    assert vault.calls == [("apikey:GEMINI_API_KEY", "secret-key-abc", None)]
    assert "apikey:GEMINI_API_KEY" not in store.data  # not in plain store


async def test_settings_write_apikey_without_vault_fails(bus):
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_write",
            "key": "apikey:GEMINI_API_KEY",
            "values": "x",
        },
        user_id="alice",
    )
    assert result["ok"] is False
    assert "vault" in result["error"].lower()


async def test_settings_write_embedding_flags_restart(bus):
    store = FakeStore()
    handler = ActionHandler(bus=bus, settings_store=store)
    result = await handler.handle(
        {
            "kind": "settings_write",
            "key": "embedding_config",
            "values": {"provider": "fastembed"},
        },
        user_id="alice",
    )
    assert result["ok"] is True
    assert result["restart_required"] is True


async def test_settings_write_no_store_fails(bus):
    handler = ActionHandler(bus=bus)
    result = await handler.handle(
        {"kind": "settings_write", "key": "llm", "values": {"default_provider": "gemini"}},
        user_id="alice",
    )
    assert result["ok"] is False
    assert "settings_store" in result["error"].lower()
