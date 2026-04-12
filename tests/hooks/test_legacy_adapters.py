from breadmind.core.tool_hooks import (
    ToolHookConfig, ToolHookResult, ToolHookRunner, ToolHookType,
)


async def test_tool_hook_runner_delegates_block():
    runner = ToolHookRunner()

    async def handler(tool_name, args):
        return ToolHookResult(action="block", block_reason="legacy-blocked")

    runner.register(ToolHookConfig(
        name="t", hook_type=ToolHookType.PRE_TOOL_USE,
        tool_pattern="*", handler=handler,
    ))
    result = await runner.run_pre_hooks("shell_exec", {"cmd": "ls"})
    assert result.action == "block"
    assert result.block_reason == "legacy-blocked"


async def test_tool_hook_runner_modify_accumulates():
    runner = ToolHookRunner()

    def h1(tool_name, args):
        return ToolHookResult(action="modify", modified_input={"cmd": "safe"})

    def h2(tool_name, args):
        return ToolHookResult(action="modify", modified_input={"note": "ok"})

    runner.register(ToolHookConfig(
        name="a", hook_type=ToolHookType.PRE_TOOL_USE, tool_pattern="*",
        handler=h1, priority=10,
    ))
    runner.register(ToolHookConfig(
        name="b", hook_type=ToolHookType.PRE_TOOL_USE, tool_pattern="*",
        handler=h2, priority=5,
    ))
    result = await runner.run_pre_hooks("shell_exec", {"cmd": "rm -rf /"})
    assert result.action == "modify"
    assert result.modified_input == {"cmd": "safe", "note": "ok"}
