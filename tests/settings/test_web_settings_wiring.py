from breadmind.core.events import EventBus
from breadmind.web.settings_wiring import (
    SettingsPipeline,
    build_settings_pipeline,
)


class FakeStore:
    def __init__(self, data=None):
        self.data = dict(data or {})

    async def get_setting(self, key):
        return self.data.get(key)

    async def set_setting(self, key, value):
        self.data[key] = value

    async def delete_setting(self, key):
        self.data.pop(key, None)


class FakeVault:
    async def store(self, *a, **k):
        return "x"

    async def delete(self, *a, **k):
        return True


async def test_build_settings_pipeline_assembles_full_stack():
    flow_bus = EventBus()
    store = FakeStore({"llm": {"default_provider": "claude"}})
    vault = FakeVault()

    pipeline = await build_settings_pipeline(
        flow_bus=flow_bus,
        settings_store=store,
        credential_vault=vault,
        message_handler=None,
        working_memory=None,
    )

    assert isinstance(pipeline, SettingsPipeline)
    assert pipeline.reload_registry is not None
    assert pipeline.settings_service is not None
    assert pipeline.action_handler is not None
    assert pipeline.approval_queue is not None
    assert pipeline.rate_limiter is not None
    assert pipeline.runtime_config_holder is not None
    assert pipeline.settings_event_bus is not None

    # Audit sink back-fill happened: service routes through action_handler.
    assert (
        pipeline.settings_service._audit_sink
        == pipeline.action_handler._record_audit
    )

    # SettingsService uses the dedicated settings_event_bus, NOT flow_bus.
    # flow_bus is the FlowEventBus which has a different API shape and would
    # blow up on SettingsService._emit_payload.
    assert pipeline.settings_service._bus is pipeline.settings_event_bus
    assert pipeline.settings_service._bus is not flow_bus


async def test_settings_event_bus_emits_on_write():
    """End-to-end: a SettingsService.set should fire on the dedicated bus."""
    from breadmind.core.events import EventType

    store = FakeStore({"persona": {"preset": "professional"}})
    pipeline = await build_settings_pipeline(
        flow_bus=EventBus(),
        settings_store=store,
        credential_vault=FakeVault(),
        message_handler=None,
        working_memory=None,
    )

    events: list[dict] = []

    async def capture(data):
        events.append(data)

    pipeline.settings_event_bus.on(EventType.SETTINGS_CHANGED.value, capture)

    result = await pipeline.settings_service.set(
        "persona", {"preset": "friendly"}, actor="user:test",
    )
    assert result.ok is True
    assert len(events) == 1
    assert events[0]["key"] == "persona"
    assert events[0]["new"] == {"preset": "friendly"}


async def test_build_settings_pipeline_seeds_runtime_config_from_store():
    store = FakeStore({
        "retry_config": {"max_attempts": 5},
        "logging_config": {"level": "INFO"},
    })
    pipeline = await build_settings_pipeline(
        flow_bus=EventBus(),
        settings_store=store,
        credential_vault=FakeVault(),
        message_handler=None,
        working_memory=None,
    )
    assert pipeline.runtime_config_holder.get("retry_config") == {"max_attempts": 5}
    assert pipeline.runtime_config_holder.get("logging_config") == {"level": "INFO"}
