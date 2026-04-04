import asyncio
import time
import pytest
from breadmind.core.protocols import ToolCall, ToolDefinition, ToolResult, ExecutionContext
from breadmind.plugins.builtin.tools.registry import HybridToolRegistry


@pytest.fixture
def registry():
    return HybridToolRegistry()


@pytest.fixture
def ctx():
    return ExecutionContext(user="test", channel="cli", session_id="s1")


def _make_readonly_tool(name: str, delay: float = 0.0) -> tuple[ToolDefinition, callable]:
    """readonly 도구 생성 헬퍼."""
    tool_def = ToolDefinition(name=name, description=f"Read {name}", parameters={}, readonly=True)

    async def executor(**kwargs):
        if delay > 0:
            await asyncio.sleep(delay)
        return f"{name}_result"

    return tool_def, executor


def _make_write_tool(name: str, delay: float = 0.0) -> tuple[ToolDefinition, callable]:
    """쓰기 도구 생성 헬퍼."""
    tool_def = ToolDefinition(name=name, description=f"Write {name}", parameters={}, readonly=False)

    async def executor(**kwargs):
        if delay > 0:
            await asyncio.sleep(delay)
        return f"{name}_result"

    return tool_def, executor


@pytest.mark.asyncio
async def test_readonly_tools_run_in_parallel(registry, ctx):
    """readonly 도구 3개 각 0.1초 → 병렬 실행 시 총 ~0.1초."""
    for i in range(3):
        tool_def, executor = _make_readonly_tool(f"read_{i}", delay=0.1)
        registry.register(tool_def, executor)

    calls = [ToolCall(id=f"tc{i}", name=f"read_{i}", arguments={}) for i in range(3)]

    start = time.monotonic()
    results = await registry.execute_batch(calls, ctx)
    elapsed = time.monotonic() - start

    assert len(results) == 3
    for i, r in enumerate(results):
        assert r.success
        assert r.output == f"read_{i}_result"

    # 병렬이면 ~0.1초, 직렬이면 ~0.3초
    assert elapsed < 0.2, f"Expected parallel execution (~0.1s), got {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_write_tools_run_serially(registry, ctx):
    """쓰기 도구는 직렬 실행."""
    execution_order = []

    for i in range(3):
        tool_def = ToolDefinition(
            name=f"write_{i}", description=f"Write {i}", parameters={}, readonly=False,
        )

        async def make_executor(idx):
            async def executor(**kwargs):
                execution_order.append(idx)
                await asyncio.sleep(0.05)
                return f"write_{idx}_result"
            return executor

        registry.register(tool_def, await make_executor(i))

    calls = [ToolCall(id=f"tc{i}", name=f"write_{i}", arguments={}) for i in range(3)]
    results = await registry.execute_batch(calls, ctx)

    assert len(results) == 3
    assert execution_order == [0, 1, 2]
    for i, r in enumerate(results):
        assert r.success
        assert r.output == f"write_{i}_result"


@pytest.mark.asyncio
async def test_mixed_batch_execution_order(registry, ctx):
    """[read1, read2, write1, read3, write2] 혼합 배치 실행 순서 검증."""
    execution_log: list[str] = []

    async def make_logging_executor(name: str):
        async def executor(**kwargs):
            execution_log.append(name)
            await asyncio.sleep(0.05)
            return f"{name}_result"
        return executor

    # read1, read2 (readonly)
    for name in ["read1", "read2"]:
        tool_def = ToolDefinition(name=name, description=name, parameters={}, readonly=True)
        registry.register(tool_def, await make_logging_executor(name))

    # write1
    tool_def = ToolDefinition(name="write1", description="write1", parameters={}, readonly=False)
    registry.register(tool_def, await make_logging_executor("write1"))

    # read3 (readonly)
    tool_def = ToolDefinition(name="read3", description="read3", parameters={}, readonly=True)
    registry.register(tool_def, await make_logging_executor("read3"))

    # write2
    tool_def = ToolDefinition(name="write2", description="write2", parameters={}, readonly=False)
    registry.register(tool_def, await make_logging_executor("write2"))

    calls = [
        ToolCall(id="tc1", name="read1", arguments={}),
        ToolCall(id="tc2", name="read2", arguments={}),
        ToolCall(id="tc3", name="write1", arguments={}),
        ToolCall(id="tc4", name="read3", arguments={}),
        ToolCall(id="tc5", name="write2", arguments={}),
    ]

    results = await registry.execute_batch(calls, ctx)

    assert len(results) == 5
    for r in results:
        assert r.success

    # 결과 순서는 원래 calls 순서와 일치해야 함
    assert results[0].output == "read1_result"
    assert results[1].output == "read2_result"
    assert results[2].output == "write1_result"
    assert results[3].output == "read3_result"
    assert results[4].output == "write2_result"

    # write1은 read1, read2 이후에 실행
    assert execution_log.index("write1") > execution_log.index("read1")
    assert execution_log.index("write1") > execution_log.index("read2")

    # read3는 write1 이후에 실행
    assert execution_log.index("read3") > execution_log.index("write1")

    # write2는 read3 이후에 실행
    assert execution_log.index("write2") > execution_log.index("read3")


@pytest.mark.asyncio
async def test_empty_calls_list(registry, ctx):
    """빈 calls 리스트 처리."""
    results = await registry.execute_batch([], ctx)
    assert results == []


@pytest.mark.asyncio
async def test_single_execute_still_works(registry, ctx):
    """기존 단일 execute() 메서드 하위 호환 확인."""
    tool_def, executor = _make_readonly_tool("single_read")
    registry.register(tool_def, executor)

    call = ToolCall(id="tc1", name="single_read", arguments={})
    result = await registry.execute(call, ctx)

    assert result.success
    assert result.output == "single_read_result"
