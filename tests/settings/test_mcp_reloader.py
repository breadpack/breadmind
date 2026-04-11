from breadmind.settings.reload_registry import SettingsReloadRegistry


class FakeMcpManager:
    def __init__(self):
        self.apply_calls = []

    async def apply_config(self, mcp_cfg=None, servers=None):
        self.apply_calls.append((mcp_cfg, servers))


class FakePluginManager:
    def __init__(self):
        self.market_calls = []

    async def apply_markets(self, markets):
        self.market_calls.append(markets)


class FakeMonitoring:
    def __init__(self):
        self.calls = []

    async def apply(self, *, monitoring_config=None, loop_protector=None,
                    scheduler_cron=None, webhook_endpoints=None):
        self.calls.append((monitoring_config, loop_protector, scheduler_cron, webhook_endpoints))


async def test_mcp_keys_trigger_manager_apply_config():
    mgr = FakeMcpManager()
    registry = SettingsReloadRegistry()

    async def reload_mcp_global(ctx):
        await mgr.apply_config(mcp_cfg=ctx["new"])

    async def reload_mcp_servers(ctx):
        await mgr.apply_config(servers=ctx["new"])

    registry.register("mcp", reload_mcp_global)
    registry.register("mcp_servers", reload_mcp_servers)

    await registry.dispatch(key="mcp", operation="set", old={}, new={"auto_discover": True})
    await registry.dispatch(key="mcp_servers", operation="set", old=[], new=[{"name": "x"}])
    assert mgr.apply_calls == [({"auto_discover": True}, None), (None, [{"name": "x"}])]


async def test_skill_markets_triggers_plugin_manager():
    plugins = FakePluginManager()
    registry = SettingsReloadRegistry()

    async def reload_markets(ctx):
        await plugins.apply_markets(ctx["new"])

    registry.register("skill_markets", reload_markets)
    await registry.dispatch(key="skill_markets", operation="set", old=[], new=[{"url": "x"}])
    assert plugins.market_calls == [[{"url": "x"}]]


async def test_monitoring_keys_trigger_monitoring_apply():
    mon = FakeMonitoring()
    registry = SettingsReloadRegistry()

    async def reload_monitoring(ctx):
        await mon.apply(monitoring_config=ctx["new"])

    async def reload_loop(ctx):
        await mon.apply(loop_protector=ctx["new"])

    async def reload_scheduler(ctx):
        await mon.apply(scheduler_cron=ctx["new"])

    async def reload_webhooks(ctx):
        await mon.apply(webhook_endpoints=ctx["new"])

    registry.register("monitoring_config", reload_monitoring)
    registry.register("loop_protector", reload_loop)
    registry.register("scheduler_cron", reload_scheduler)
    registry.register("webhook_endpoints", reload_webhooks)

    await registry.dispatch(key="monitoring_config", operation="set", old={}, new={"enabled": True})
    await registry.dispatch(key="loop_protector", operation="set", old={}, new={"cooldown_minutes": 5})
    await registry.dispatch(key="scheduler_cron", operation="set", old={}, new={"enabled": False})
    await registry.dispatch(key="webhook_endpoints", operation="set", old=[], new=[{"url": "x"}])

    assert len(mon.calls) == 4
