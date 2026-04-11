from breadmind.settings.reload_registry import SettingsReloadRegistry


class FakeGuard:
    def __init__(self):
        self.blacklist = []
        self.approval = {}
        self.permissions = {}
        self.tool_security = {}

    def reload(self, **kwargs):
        for k, v in kwargs.items():
            if v is not None:
                setattr(self, k, v)


async def test_safety_keys_reload_guard():
    guard = FakeGuard()
    registry = SettingsReloadRegistry()

    async def reload_bl(ctx):
        guard.reload(blacklist=ctx["new"])

    async def reload_appr(ctx):
        guard.reload(approval=ctx["new"])

    async def reload_perm(ctx):
        guard.reload(permissions=ctx["new"])

    async def reload_tool(ctx):
        guard.reload(tool_security=ctx["new"])

    registry.register("safety_blacklist", reload_bl)
    registry.register("safety_approval", reload_appr)
    registry.register("safety_permissions", reload_perm)
    registry.register("tool_security", reload_tool)

    await registry.dispatch(key="safety_blacklist", operation="set", old=[], new=["rm -rf /"])
    await registry.dispatch(key="safety_approval", operation="set", old={}, new={"cmd": True})
    await registry.dispatch(key="safety_permissions", operation="set", old={}, new={"shell": "admin"})
    await registry.dispatch(key="tool_security", operation="set", old={}, new={"command_whitelist_enabled": True})

    assert guard.blacklist == ["rm -rf /"]
    assert guard.approval == {"cmd": True}
    assert guard.permissions == {"shell": "admin"}
    assert guard.tool_security == {"command_whitelist_enabled": True}
