"""Full-stack smoke test: agent tool call → SettingsService → hot reload."""
from breadmind.core.events import EventBus, EventType
from breadmind.settings.approval_queue import PendingApprovalQueue
from breadmind.settings.llm_holder import LLMProviderHolder
from breadmind.settings.reload_registry import SettingsReloadRegistry
from breadmind.settings.service import SettingsService
from breadmind.tools.registry import ToolRegistry
from breadmind.tools.settings_tool_registration import register_settings_tools


class InMemoryStore:
    def __init__(self, data=None):
        self.data = dict(data or {})

    async def get_setting(self, key):
        return self.data.get(key)

    async def set_setting(self, key, value):
        self.data[key] = value

    async def delete_setting(self, key):
        self.data.pop(key, None)


class InMemoryVault:
    def __init__(self):
        self.store_map = {}

    async def store(self, cred_id, value, metadata=None):
        self.store_map[cred_id] = value
        return cred_id

    async def delete(self, cred_id):
        self.store_map.pop(cred_id, None)
        return True


async def _noop_audit(**kwargs):
    return 1


class FakeProvider:
    def __init__(self, name):
        self.name = name


async def test_agent_tool_call_hot_reloads_llm_provider():
    """Full happy path: tool call → service → registry → holder swap + event."""
    bus = EventBus()
    events = []

    async def capture(data):
        events.append(data)

    bus.on(EventType.SETTINGS_CHANGED.value, capture)

    store = InMemoryStore({"llm": {"default_provider": "claude"}})
    vault = InMemoryVault()
    registry = SettingsReloadRegistry()
    service = SettingsService(
        store=store,
        vault=vault,
        audit_sink=_noop_audit,
        reload_registry=registry,
        event_bus=bus,
        approval_queue=PendingApprovalQueue(),
    )

    holder = LLMProviderHolder(FakeProvider("claude"))

    async def _reload_llm(ctx):
        # Stub the real create_provider; in production this would rebuild
        # the provider from updated config + vault state.
        new_name = ctx["new"]["default_provider"]
        holder.swap(FakeProvider(new_name))

    registry.register("llm", _reload_llm)

    tool_registry = ToolRegistry()
    register_settings_tools(tool_registry, service=service, actor="agent:core")

    # Invoke the tool through its registered callable.
    fn = tool_registry._tools.get("breadmind_set_setting")
    assert fn is not None, "breadmind_set_setting not registered"

    result = await fn(
        key="llm",
        value='{"default_provider":"gemini","default_model":"gemini-2.0-flash"}',
    )

    # 1. Tool returned an OK line with hot_reloaded=true.
    assert result.startswith("OK"), f"Expected OK, got: {result}"
    assert "hot_reloaded=true" in result

    # 2. Holder's inner provider was swapped.
    assert holder.name == "gemini"

    # 3. Store was updated.
    assert store.data["llm"]["default_provider"] == "gemini"

    # 4. SETTINGS_CHANGED event fired with agent:core as actor.
    assert len(events) == 1
    assert events[0]["key"] == "llm"
    assert events[0]["actor"] == "agent:core"
    assert events[0]["new"] == {
        "default_provider": "gemini",
        "default_model": "gemini-2.0-flash",
    }


async def test_agent_tool_call_to_admin_key_goes_to_approval():
    """Agent writing a safety-blacklist admin key hits the approval queue."""
    store = InMemoryStore()
    vault = InMemoryVault()
    approval_queue = PendingApprovalQueue()
    registry = SettingsReloadRegistry()
    service = SettingsService(
        store=store,
        vault=vault,
        audit_sink=_noop_audit,
        reload_registry=registry,
        event_bus=EventBus(),
        approval_queue=approval_queue,
    )

    tool_registry = ToolRegistry()
    register_settings_tools(tool_registry, service=service, actor="agent:core")

    fn = tool_registry._tools.get("breadmind_set_setting")
    result = await fn(
        key="safety_blacklist",
        value='{"default":["rm -rf /"]}',
    )

    assert result.startswith("PENDING:"), (
        f"Expected PENDING, got: {result}"
    )
    assert "approval_id=approve-" in result
    # Nothing persisted yet.
    assert store.data.get("safety_blacklist") is None

    # Resolving the approval runs the queued write.
    pending = approval_queue.list_pending()
    assert len(pending) == 1
    resolved = await service.resolve_approval(pending[0].id)
    assert resolved.ok is True
    assert resolved.persisted is True
    assert store.data["safety_blacklist"] == {"default": ["rm -rf /"]}
