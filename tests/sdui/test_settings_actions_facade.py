"""Task 6: ActionHandler delegates settings_write into SettingsService.

Verifies that when ActionHandler is wired with an ``event_bus``, a
``settings_write`` action for a non-credential key emits SETTINGS_CHANGED
with the correct actor/key payload. This proves the delegation is in place
and the event pipeline is wired end-to-end.
"""
from breadmind.core.events import EventBus, EventType
from breadmind.sdui.actions import ActionHandler


class FakeStore:
    def __init__(self):
        self.data: dict = {}

    async def get_setting(self, key):
        return self.data.get(key)

    async def set_setting(self, key, value):
        self.data[key] = value

    async def delete_setting(self, key):
        self.data.pop(key, None)


class FakeVault:
    def __init__(self):
        self.store_calls: list = []
        self.delete_calls: list = []

    async def store(self, cred_id, value, metadata=None):
        self.store_calls.append((cred_id, value, metadata))
        return cred_id

    async def delete(self, cred_id):
        self.delete_calls.append(cred_id)
        return True


class FakeBus:
    async def async_emit(self, event, data=None):
        pass


async def test_action_handler_set_emits_settings_changed_event():
    bus = EventBus()
    events: list = []

    async def capture(data):
        events.append(data)

    bus.on(EventType.SETTINGS_CHANGED.value, capture)

    handler = ActionHandler(
        bus=FakeBus(),
        settings_store=FakeStore(),
        credential_vault=FakeVault(),
        event_bus=bus,
    )
    result = await handler.handle(
        {
            "kind": "settings_write",
            "key": "persona",
            "values": {"preset": "friendly"},
        },
        user_id="u1",
    )
    assert result["ok"] is True
    assert result["persisted"] is True
    assert len(events) == 1
    assert events[0]["key"] == "persona"
    assert events[0]["actor"] == "user:u1"
