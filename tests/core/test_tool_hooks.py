"""Tests for tool pre/post execution hooks."""

from breadmind.core.tool_hooks import (
    ToolHookConfig,
    ToolHookResult,
    ToolHookRunner,
    ToolHookType,
)


async def test_pre_hook_blocks_execution():
    runner = ToolHookRunner()

    def blocker(tool_name, arguments):
        return ToolHookResult(action="block", block_reason="dangerous command")

    runner.register(
        ToolHookConfig(
            name="blocker",
            hook_type=ToolHookType.PRE_TOOL_USE,
            tool_pattern="shell_*",
            handler=blocker,
        )
    )
    result = await runner.run_pre_hooks("shell_exec", {"cmd": "rm -rf /"})
    assert result.action == "block"
    assert result.block_reason == "dangerous command"


async def test_pre_hook_modifies_arguments():
    runner = ToolHookRunner()

    def modifier(tool_name, arguments):
        return ToolHookResult(
            action="modify", modified_input={"cmd": "echo safe"}
        )

    runner.register(
        ToolHookConfig(
            name="modifier",
            hook_type=ToolHookType.PRE_TOOL_USE,
            tool_pattern="*",
            handler=modifier,
        )
    )
    result = await runner.run_pre_hooks("shell_exec", {"cmd": "rm -rf /"})
    assert result.action == "modify"
    assert result.modified_input == {"cmd": "echo safe"}


async def test_pre_hook_continues_unchanged():
    runner = ToolHookRunner()

    def passthrough(tool_name, arguments):
        return ToolHookResult(action="continue")

    runner.register(
        ToolHookConfig(
            name="passthrough",
            hook_type=ToolHookType.PRE_TOOL_USE,
            tool_pattern="*",
            handler=passthrough,
        )
    )
    result = await runner.run_pre_hooks("some_tool", {"key": "value"})
    assert result.action == "continue"
    assert result.modified_input is None


async def test_post_hook_injects_context():
    runner = ToolHookRunner()

    def annotator(tool_name, arguments, result, success):
        return ToolHookResult(additional_context="[audit: logged]")

    runner.register(
        ToolHookConfig(
            name="annotator",
            hook_type=ToolHookType.POST_TOOL_USE,
            tool_pattern="*",
            handler=annotator,
        )
    )
    result = await runner.run_post_hooks("shell_exec", {}, "output", True)
    assert result.additional_context == "[audit: logged]"


async def test_hook_priority_ordering():
    runner = ToolHookRunner()
    call_order = []

    def hook_a(tool_name, arguments):
        call_order.append("a")
        return ToolHookResult()

    def hook_b(tool_name, arguments):
        call_order.append("b")
        return ToolHookResult()

    runner.register(
        ToolHookConfig(
            name="low",
            hook_type=ToolHookType.PRE_TOOL_USE,
            tool_pattern="*",
            handler=hook_a,
            priority=1,
        )
    )
    runner.register(
        ToolHookConfig(
            name="high",
            hook_type=ToolHookType.PRE_TOOL_USE,
            tool_pattern="*",
            handler=hook_b,
            priority=10,
        )
    )
    await runner.run_pre_hooks("test_tool", {})
    assert call_order == ["b", "a"]


async def test_hook_pattern_matching_glob():
    runner = ToolHookRunner()
    called = []

    def handler(tool_name, arguments):
        called.append(tool_name)
        return ToolHookResult()

    runner.register(
        ToolHookConfig(
            name="shell_only",
            hook_type=ToolHookType.PRE_TOOL_USE,
            tool_pattern="shell_*",
            handler=handler,
        )
    )
    await runner.run_pre_hooks("shell_exec", {})
    await runner.run_pre_hooks("file_read", {})
    assert called == ["shell_exec"]


async def test_hook_pattern_wildcard_matches_all():
    runner = ToolHookRunner()
    called = []

    def handler(tool_name, arguments):
        called.append(tool_name)
        return ToolHookResult()

    runner.register(
        ToolHookConfig(
            name="all",
            hook_type=ToolHookType.PRE_TOOL_USE,
            tool_pattern="*",
            handler=handler,
        )
    )
    await runner.run_pre_hooks("shell_exec", {})
    await runner.run_pre_hooks("file_read", {})
    assert called == ["shell_exec", "file_read"]


async def test_unregister_hook():
    runner = ToolHookRunner()

    def handler(tool_name, arguments):
        return ToolHookResult(action="block", block_reason="blocked")

    runner.register(
        ToolHookConfig(
            name="removable",
            hook_type=ToolHookType.PRE_TOOL_USE,
            tool_pattern="*",
            handler=handler,
        )
    )
    assert runner.unregister("removable") is True
    assert runner.unregister("removable") is False
    result = await runner.run_pre_hooks("test", {})
    assert result.action == "continue"


async def test_async_hook_handler():
    runner = ToolHookRunner()

    async def async_handler(tool_name, arguments, result, success):
        return ToolHookResult(additional_context="async context")

    runner.register(
        ToolHookConfig(
            name="async_hook",
            hook_type=ToolHookType.POST_TOOL_USE,
            tool_pattern="*",
            handler=async_handler,
        )
    )
    result = await runner.run_post_hooks("test", {}, "output", True)
    assert result.additional_context == "async context"


async def test_multiple_pre_hooks_aggregate():
    runner = ToolHookRunner()

    def modifier_a(tool_name, arguments):
        modified = dict(arguments)
        modified["extra_a"] = True
        return ToolHookResult(action="modify", modified_input=modified)

    def modifier_b(tool_name, arguments):
        modified = dict(arguments)
        modified["extra_b"] = True
        return ToolHookResult(action="modify", modified_input=modified)

    runner.register(
        ToolHookConfig(
            name="mod_a",
            hook_type=ToolHookType.PRE_TOOL_USE,
            tool_pattern="*",
            handler=modifier_a,
            priority=10,
        )
    )
    runner.register(
        ToolHookConfig(
            name="mod_b",
            hook_type=ToolHookType.PRE_TOOL_USE,
            tool_pattern="*",
            handler=modifier_b,
            priority=5,
        )
    )
    result = await runner.run_pre_hooks("test", {"original": True})
    assert result.action == "modify"
    assert result.modified_input["original"] is True
    assert result.modified_input["extra_a"] is True
    assert result.modified_input["extra_b"] is True
