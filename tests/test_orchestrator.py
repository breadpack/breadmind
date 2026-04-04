import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.core.orchestrator import Orchestrator
from breadmind.core.role_registry import RoleRegistry
from breadmind.core.result_evaluator import ResultEvaluator
from breadmind.llm.base import LLMResponse, TokenUsage


def _resp(content):
    return LLMResponse(
        content=content, tool_calls=[],
        usage=TokenUsage(input_tokens=10, output_tokens=10),
        stop_reason="end_turn",
    )


def _plan_response(nodes):
    return _resp(json.dumps({"nodes": nodes}))


@pytest.mark.asyncio
async def test_orchestrator_plans_and_executes():
    call_idx = 0

    async def mock_chat(**kwargs):
        nonlocal call_idx
        call_idx += 1
        if call_idx == 1:
            return _plan_response([
                {"id": "t1", "description": "Check pods", "role": "k8s_diagnostician",
                 "depends_on": [], "difficulty": "low", "expected_output": "Pod list"},
            ])
        elif call_idx == 2:
            return _resp("Found 3 healthy pods")
        else:
            return _resp("All 3 pods are healthy. No issues found.")

    provider = AsyncMock()
    provider.chat = AsyncMock(side_effect=mock_chat)

    registry = MagicMock()
    registry.get_all_definitions = MagicMock(return_value=[])

    orch = Orchestrator(
        provider=provider, role_registry=RoleRegistry(),
        evaluator=ResultEvaluator(), tool_registry=registry,
    )
    result = await orch.run("K8s Pod 상태 확인해줘", user="test", channel="test")
    assert result
    assert len(result) > 5


@pytest.mark.asyncio
async def test_orchestrator_handles_all_failures_gracefully():
    call_idx = 0

    async def mock_chat(**kwargs):
        nonlocal call_idx
        call_idx += 1
        if call_idx == 1:
            return _plan_response([
                {"id": "t1", "description": "Check pods", "role": "k8s_diagnostician",
                 "depends_on": [], "difficulty": "low", "expected_output": "Pod list"},
            ])
        elif call_idx <= 4:
            # SubAgent calls: always fail (original + 2 retries)
            return _resp("[success=False] Connection refused")
        elif call_idx == 5:
            # Replan call
            return _plan_response([
                {"id": "task_alt_1", "description": "Try alternative", "role": "general_analyst",
                 "depends_on": [], "difficulty": "medium", "expected_output": "Result"},
            ])
        elif call_idx == 6:
            # Alt subagent
            return _resp("[success=False] Still failing")
        else:
            # Summary
            return _resp("Task failed after retries and replan.")

    provider = AsyncMock()
    provider.chat = AsyncMock(side_effect=mock_chat)

    registry = MagicMock()
    registry.get_all_definitions = MagicMock(return_value=[])

    orch = Orchestrator(
        provider=provider, role_registry=RoleRegistry(),
        evaluator=ResultEvaluator(), tool_registry=registry,
    )
    result = await orch.run("Check something", user="test", channel="test")
    assert result  # Should still return a summary even with all failures
