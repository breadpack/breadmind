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

    # Audit sink back-fill happened: service routes through action_handler.
    assert (
        pipeline.settings_service._audit_sink
        == pipeline.action_handler._record_audit
    )


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
