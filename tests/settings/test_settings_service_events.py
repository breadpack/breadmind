from breadmind.core.events import EventBus, EventType
from breadmind.settings.reload_registry import SettingsReloadRegistry
from breadmind.settings.service import SettingsService


class FakeStore:
    def __init__(self):
        self.data = {"persona": {"preset": "professional"}}

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


async def test_set_emits_settings_changed_event():
    bus = EventBus()
    events: list[dict] = []

    async def capture(data):
        events.append(data)

    bus.on(EventType.SETTINGS_CHANGED.value, capture)

    svc = SettingsService(
        store=FakeStore(),
        vault=FakeVault(),
        audit_sink=_noop_audit,
        reload_registry=SettingsReloadRegistry(),
        event_bus=bus,
    )

    result = await svc.set("persona", {"preset": "friendly"}, actor="agent:core")
    assert result.ok
    assert len(events) == 1
    ev = events[0]
    assert ev["key"] == "persona"
    assert ev["operation"] == "set"
    assert ev["old"] == {"preset": "professional"}
    assert ev["new"] == {"preset": "friendly"}
    assert ev["actor"] == "agent:core"


async def test_credential_event_masks_plaintext():
    bus = EventBus()
    events: list[dict] = []

    async def capture(data):
        events.append(data)

    bus.on(EventType.SETTINGS_CHANGED.value, capture)

    svc = SettingsService(
        store=FakeStore(),
        vault=FakeVault(),
        audit_sink=_noop_audit,
        reload_registry=SettingsReloadRegistry(),
        event_bus=bus,
    )

    await svc.set_credential(
        "apikey:anthropic", "sk-ant-secret", actor="agent:core"
    )
    assert len(events) == 1
    assert events[0]["old"] is None
    assert events[0]["new"] is None
    # Plaintext never reaches the bus.
    assert "sk-ant-secret" not in str(events[0])
