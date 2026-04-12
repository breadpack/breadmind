import json
import pytest
from unittest.mock import AsyncMock
from breadmind.core.planner import Planner
from breadmind.core.role_registry import RoleRegistry
from breadmind.llm.base import LLMResponse, TokenUsage


def _make_plan_response(nodes: list[dict]) -> LLMResponse:
    return LLMResponse(
        content=json.dumps({"nodes": nodes}),
        tool_calls=[], usage=TokenUsage(input_tokens=100, output_tokens=200),
        stop_reason="end_turn",
    )


@pytest.mark.asyncio
async def test_planner_creates_dag():
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=_make_plan_response([
        {"id": "task_1", "description": "Find OOMKilled pods", "role": "k8s_diagnostician",
         "depends_on": [], "difficulty": "low", "expected_output": "Pod list"},
        {"id": "task_2", "description": "Update memory limits", "role": "k8s_executor",
         "depends_on": ["task_1"], "difficulty": "medium", "expected_output": "Limits updated"},
    ]))
    planner = Planner(provider=provider, role_registry=RoleRegistry())
    dag = await planner.plan("OOMKilled Pod 찾아서 메모리 2배로 올려줘")
    assert dag.goal == "OOMKilled Pod 찾아서 메모리 2배로 올려줘"
    assert len(dag.nodes) == 2
    assert dag.nodes["task_1"].depends_on == []
    assert dag.nodes["task_2"].depends_on == ["task_1"]
    assert dag.nodes["task_1"].difficulty == "low"


@pytest.mark.asyncio
async def test_planner_handles_invalid_json():
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=LLMResponse(
        content="I cannot parse this request",
        tool_calls=[], usage=TokenUsage(input_tokens=10, output_tokens=10),
        stop_reason="end_turn",
    ))
    planner = Planner(provider=provider, role_registry=RoleRegistry())
    dag = await planner.plan("do something")
    assert len(dag.nodes) == 1
    node = list(dag.nodes.values())[0]
    assert node.role == "general_analyst"


@pytest.mark.asyncio
async def test_planner_injects_role_summaries():
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=_make_plan_response([
        {"id": "task_1", "description": "check", "role": "general_analyst",
         "depends_on": [], "difficulty": "low", "expected_output": "result"},
    ]))
    planner = Planner(provider=provider, role_registry=RoleRegistry())
    await planner.plan("check something")
    call_args = provider.chat.call_args
    messages = call_args.kwargs.get("messages") or call_args[0][0]
    system_content = messages[0].content
    assert "k8s_diagnostician" in system_content
