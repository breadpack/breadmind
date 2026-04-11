from breadmind.settings.llm_holder import LLMProviderHolder
from breadmind.settings.reload_registry import SettingsReloadRegistry


class FakeProvider:
    def __init__(self, name):
        self.name = name


def fake_factory(config):
    return FakeProvider(config["default_provider"])


async def test_llm_key_change_swaps_provider_in_holder():
    holder = LLMProviderHolder(FakeProvider("claude"))
    registry = SettingsReloadRegistry()

    async def reload_llm(ctx):
        holder.swap(fake_factory(ctx["new"]))

    registry.register("llm", reload_llm)

    await registry.dispatch(
        key="llm",
        operation="set",
        old={"default_provider": "claude"},
        new={"default_provider": "gemini"},
    )
    assert holder.name == "gemini"


async def test_apikey_change_also_reloads_provider():
    holder = LLMProviderHolder(FakeProvider("claude-old"))
    registry = SettingsReloadRegistry()
    calls = []

    async def reload_llm(ctx):
        calls.append(ctx["key"])
        holder.swap(FakeProvider("claude-new"))

    registry.register("apikey:*", reload_llm)
    await registry.dispatch(
        key="apikey:anthropic", operation="credential_store", old=None, new=None
    )
    assert calls == ["apikey:anthropic"]
    assert holder.name == "claude-new"


async def test_reloader_closes_old_inner_on_swap():
    """When a reloader swaps the inner provider, it should release the old one."""
    closed = []

    class ClosableProvider:
        def __init__(self, name):
            self.name = name

        async def close(self):
            closed.append(self.name)

    holder = LLMProviderHolder(ClosableProvider("old"))
    registry = SettingsReloadRegistry()

    async def reload_llm(ctx):
        old = holder.current
        holder.swap(ClosableProvider("new"))
        if old is not holder.current:
            await old.close()

    registry.register("llm", reload_llm)
    await registry.dispatch(
        key="llm",
        operation="set",
        old={"default_provider": "claude"},
        new={"default_provider": "gemini"},
    )
    assert closed == ["old"]
    assert holder.name == "new"
