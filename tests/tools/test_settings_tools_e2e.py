"""End-to-end wiring tests for ``register_settings_tools``.

These exercise the thin registration entry point that binds the eight
``breadmind_*_setting`` tools onto a real :class:`ToolRegistry`, and verify
that a tool invoked through the registry actually hits the
``SettingsService`` write pipeline (validation + persistence).
"""
from breadmind.core.events import EventBus
from breadmind.settings.reload_registry import SettingsReloadRegistry
from breadmind.settings.service import SettingsService
from breadmind.tools.registry import ToolRegistry
from breadmind.tools.settings_tool_registration import register_settings_tools


class FakeStore:
    def __init__(self) -> None:
        self.data: dict = {}

    async def get_setting(self, key):
        return self.data.get(key)

    async def set_setting(self, key, value):
        self.data[key] = value

    async def delete_setting(self, key):
        self.data.pop(key, None)


class FakeVault:
    async def store(self, cred_id, value, metadata=None):
        return cred_id

    async def delete(self, cred_id):
        return True


async def _noop_audit(**kwargs):
    return 1


EXPECTED_TOOL_NAMES = {
    "breadmind_get_setting",
    "breadmind_list_settings",
    "breadmind_set_setting",
    "breadmind_append_setting",
    "breadmind_update_setting_item",
    "breadmind_delete_setting_item",
    "breadmind_set_credential",
    "breadmind_delete_credential",
}


async def test_register_settings_tools_adds_eight_entries():
    registry = ToolRegistry()
    service = SettingsService(
        store=FakeStore(),
        vault=FakeVault(),
        audit_sink=_noop_audit,
        reload_registry=SettingsReloadRegistry(),
        event_bus=EventBus(),
    )
    register_settings_tools(registry, service=service, actor="agent:core")

    names = set(registry.list_tools())
    assert EXPECTED_TOOL_NAMES.issubset(names)


async def test_registered_set_setting_actually_persists():
    registry = ToolRegistry()
    store = FakeStore()
    store.data["persona"] = {"preset": "professional"}
    service = SettingsService(
        store=store,
        vault=FakeVault(),
        audit_sink=_noop_audit,
        reload_registry=SettingsReloadRegistry(),
        event_bus=EventBus(),
    )
    register_settings_tools(registry, service=service, actor="agent:core")

    tool_fn = registry._tools.get("breadmind_set_setting")
    assert tool_fn is not None
    result = await tool_fn(key="persona", value='{"preset":"friendly"}')
    assert result.startswith("OK")
    assert store.data["persona"] == {"preset": "friendly"}
