"""End-to-end integration test for Orchestrator pipeline."""
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


@pytest.mark.asyncio
async def test_full_pipeline_multi_domain():
    """Test: K8s + Proxmox parallel diagnosis -> sequential fix -> summary."""
    call_seq = []

    async def mock_chat(**kwargs):
        messages = kwargs.get("messages") or []
        system = messages[0].content if messages else ""
        user_msg = next((m.content for m in messages if m.role == "user"), "")

        if "task planner" in system.lower():
            call_seq.append("planner")
            return _resp(json.dumps({"nodes": [
                {"id": "t1", "description": "Check K8s pods", "role": "k8s_diagnostician",
                 "depends_on": [], "difficulty": "low", "expected_output": "Pod status"},
                {"id": "t2", "description": "Check Proxmox VMs", "role": "proxmox_diagnostician",
                 "depends_on": [], "difficulty": "low", "expected_output": "VM status"},
                {"id": "t3", "description": "Fix K8s issue", "role": "k8s_executor",
                 "depends_on": ["t1"], "difficulty": "medium", "expected_output": "Issue fixed"},
            ]}))
        elif "diagnostics" in system.lower() or "diagnostician" in system.lower():
            call_seq.append(f"subagent:diag")
            return _resp(f"[OK] All healthy for: {user_msg[:30]}")
        elif "operations" in system.lower() or "executor" in system.lower():
            call_seq.append("subagent:executor")
            return _resp("Fixed: scaled deployment to 3 replicas")
        elif "summarizing" in system.lower():
            call_seq.append("summary")
            return _resp("All systems healthy. K8s scaled to 3 replicas. Proxmox VMs running.")
        else:
            call_seq.append("other")
            return _resp("OK")

    provider = AsyncMock()
    provider.chat = AsyncMock(side_effect=mock_chat)

    registry = MagicMock()
    registry.get_all_definitions = MagicMock(return_value=[])
    registry.execute = AsyncMock()

    orch = Orchestrator(
        provider=provider, role_registry=RoleRegistry(),
        evaluator=ResultEvaluator(), tool_registry=registry,
    )

    result = await orch.run(
        "K8s Pod 상태 확인하고 문제 있으면 고쳐줘, Proxmox VM도 확인해",
        user="admin", channel="web",
    )

    assert call_seq[0] == "planner"
    assert "summary" in call_seq
    assert result
    assert len(result) > 10
