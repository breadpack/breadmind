from breadmind.core.lifecycle_hooks import (
    LifecycleEvent, LifecycleHookResult, LifecycleHookRunner,
)
from breadmind.core.tool_hooks import (
    ToolHookConfig, ToolHookResult, ToolHookRunner, ToolHookType,
)
from breadmind.plugins.builtin.safety.hooks import (
    HookDefinition as ShellHookDef,
    HookRunner as ShellRunner,
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


async def test_lifecycle_user_prompt_submit_modifies_input():
    runner = LifecycleHookRunner()

    def h(data):
        return LifecycleHookResult(
            allow=True, modified_input="sanitized: " + data["prompt"],
        )

    runner.on(LifecycleEvent.USER_PROMPT_SUBMIT, h)
    result = await runner.emit(
        LifecycleEvent.USER_PROMPT_SUBMIT,
        {"prompt": "rm -rf /"},
    )
    assert result.allow is True
    assert result.modified_input == "sanitized: rm -rf /"


async def test_lifecycle_blocks_when_any_denies():
    runner = LifecycleHookRunner()
    runner.on(LifecycleEvent.USER_PROMPT_SUBMIT, lambda d: LifecycleHookResult(allow=False))
    runner.on(LifecycleEvent.USER_PROMPT_SUBMIT, lambda d: LifecycleHookResult(allow=True))
    result = await runner.emit(
        LifecycleEvent.USER_PROMPT_SUBMIT, {"prompt": "x"},
    )
    assert result.allow is False


async def test_shell_runner_blocks_nonzero_pre():
    runner = ShellRunner()
    runner.register(ShellHookDef(
        event="pre_tool_use",
        tool_pattern="*",
        command="import sys; sys.exit(1)",
        shell="python",
    ))
    result = await runner.run_pre_tool_use("shell_exec", {"cmd": "ls"})
    assert result.passed is False


async def test_shell_runner_passes_zero():
    runner = ShellRunner()
    runner.register(ShellHookDef(
        event="pre_tool_use",
        tool_pattern="*",
        command="pass",
        shell="python",
    ))
    result = await runner.run_pre_tool_use("shell_exec", {"cmd": "ls"})
    assert result.passed is True
