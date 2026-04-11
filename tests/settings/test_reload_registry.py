from breadmind.settings.reload_registry import SettingsReloadRegistry


async def test_exact_key_match_runs_reload_fn():
    registry = SettingsReloadRegistry()
    calls = []

    async def reload_llm(ctx):
        calls.append(ctx["new"])

    registry.register("llm", reload_llm)
    result = await registry.dispatch(
        key="llm", operation="set", old=None, new={"default_provider": "gemini"}
    )
    assert result.all_ok is True
    assert result.ran == ["llm"]
    assert calls == [{"default_provider": "gemini"}]


async def test_prefix_glob_matches_credential_keys():
    registry = SettingsReloadRegistry()
    calls = []

    async def reload_credential(ctx):
        calls.append(ctx["key"])

    registry.register("apikey:*", reload_credential)
    result = await registry.dispatch(
        key="apikey:anthropic", operation="credential_store", old=None, new=None
    )
    assert result.all_ok is True
    assert calls == ["apikey:anthropic"]


async def test_non_matching_key_runs_nothing():
    registry = SettingsReloadRegistry()
    registry.register("llm", lambda ctx: None)
    result = await registry.dispatch(
        key="persona", operation="set", old=None, new="friendly"
    )
    assert result.all_ok is True
    assert result.ran == []


async def test_failure_isolated_per_subscriber():
    registry = SettingsReloadRegistry()

    async def good(ctx):
        ctx["good"] = True

    async def bad(ctx):
        raise RuntimeError("boom")

    seen = {}
    async def probe(ctx):
        seen.update(ctx)

    registry.register("llm", good)
    registry.register("llm", bad)
    registry.register("llm", probe)

    result = await registry.dispatch(key="llm", operation="set", old=None, new={})
    assert result.all_ok is False
    assert "bad" in "".join(result.errors.keys()) or any(
        "boom" in v for v in result.errors.values()
    )
    # Both non-failing subscribers still ran.
    assert len(result.ran) == 3


async def test_sync_reload_fn_wrapped_in_thread():
    registry = SettingsReloadRegistry()
    calls = []

    def sync_reload(ctx):
        calls.append(ctx["key"])

    registry.register("persona", sync_reload)
    result = await registry.dispatch(
        key="persona", operation="set", old="a", new="b"
    )
    assert result.all_ok is True
    assert calls == ["persona"]
