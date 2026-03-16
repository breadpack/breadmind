import pytest
from unittest.mock import AsyncMock
from breadmind.core.analyzers import (
    DiskUsageAnalyzer, MemoryUsageAnalyzer, K8sPodAnalyzer, run_all_analyzers,
)
from breadmind.tools.registry import ToolResult


@pytest.fixture
def mock_executor():
    async def executor(tool_name, args):
        return ToolResult(success=True, output="")
    return executor


@pytest.mark.asyncio
async def test_disk_usage_critical():
    async def executor(tool_name, args):
        return ToolResult(success=True, output=" 95% /\n 50% /home\n")
    results = await DiskUsageAnalyzer().analyze(executor)
    assert len(results) == 1
    assert results[0].severity == "critical"
    assert "95%" in results[0].title


@pytest.mark.asyncio
async def test_k8s_pod_crashloop():
    async def executor(tool_name, args):
        return ToolResult(success=True, output=(
            "NAMESPACE   NAME        READY   STATUS             RESTARTS\n"
            "default     nginx-abc   0/1     CrashLoopBackOff   5\n"
        ))
    results = await K8sPodAnalyzer().analyze(executor)
    assert len(results) == 1
    assert results[0].severity == "critical"
    assert "CrashLoopBackOff" in results[0].title


@pytest.mark.asyncio
async def test_run_all_analyzers(mock_executor):
    results = await run_all_analyzers(mock_executor)
    assert isinstance(results, list)
