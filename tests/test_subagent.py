import pytest
from unittest.mock import AsyncMock
from breadmind.core.subagent import SubAgent
from breadmind.llm.base import LLMResponse, ToolCall, TokenUsage


def _make_response(content, tool_calls=None):
    return LLMResponse(
        content=content, tool_calls=tool_calls or [],
        usage=TokenUsage(input_tokens=10, output_tokens=10),
        stop_reason="end_turn",
    )


@pytest.mark.asyncio
async def test_subagent_runs_simple_task():
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=_make_response("Found 3 OOMKilled pods"))
    agent = SubAgent(
        task_id="task_1", description="Find OOMKilled pods",
        role="k8s_diagnostician", provider=provider,
        tools=[], system_prompt="You are a K8s diagnostician.", max_turns=3,
    )
    result = await agent.run(context={})
    assert result.success is True
    assert "OOMKilled" in result.output


@pytest.mark.asyncio
async def test_subagent_executes_tool_calls():
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=_make_response("Done: 3 pods found"))
    registry_execute = AsyncMock(return_value=type("R", (), {"success": True, "output": "pod-1\npod-2", "not_found": False})())
    agent = SubAgent(
        task_id="task_1", description="List pods",
        role="k8s_diagnostician", provider=provider,
        tools=[{"name": "pods_list", "description": "List pods", "parameters": {}}],
        system_prompt="You are a K8s diagnostician.", max_turns=3,
        tool_executor=registry_execute,
    )
    result = await agent.run(context={})
    assert result.success is True


@pytest.mark.asyncio
async def test_subagent_max_turns_exceeded():
    tc = ToolCall(id="tc1", name="pods_list", arguments={})
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=_make_response(None, tool_calls=[tc]))
    registry_execute = AsyncMock(return_value=type("R", (), {"success": True, "output": "data", "not_found": False})())
    agent = SubAgent(
        task_id="task_1", description="Endless task",
        role="k8s_diagnostician", provider=provider,
        tools=[{"name": "pods_list", "description": "List pods", "parameters": {}}],
        system_prompt="You are a K8s diagnostician.", max_turns=2,
        tool_executor=registry_execute,
    )
    result = await agent.run(context={})
    assert result.success is False


@pytest.mark.asyncio
async def test_subagent_injects_context():
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=_make_response("Memory updated"))
    agent = SubAgent(
        task_id="task_2", description="Update memory limits",
        role="k8s_executor", provider=provider,
        tools=[], system_prompt="You are a K8s executor.", max_turns=3,
    )
    context = {"task_1": "Found pods: pod-a (128Mi), pod-b (256Mi)"}
    await agent.run(context=context)
    call_args = provider.chat.call_args
    messages = call_args.kwargs.get("messages") or call_args[0][0]
    context_in_messages = any("pod-a" in (m.content or "") for m in messages)
    assert context_in_messages
