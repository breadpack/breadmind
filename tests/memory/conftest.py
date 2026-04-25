"""Shared fixtures for tests/memory/."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from breadmind.core.agent import CoreAgent
from breadmind.core.safety import SafetyGuard
from breadmind.core.tool_executor import ToolExecutor
from breadmind.llm.base import LLMResponse, TokenUsage
from breadmind.memory.signals import SignalDetector
from breadmind.memory.working import WorkingMemory
from breadmind.tools.registry import ToolRegistry, tool


@tool(description="Memory test tool")
async def _mem_test_tool(input: str = "") -> str:  # pragma: no cover - rarely run
    return f"result: {input}"


_mem_test_tool._tool_definition.name = "test_tool"


@pytest.fixture
def make_agent():
    """Build a CoreAgent with mocked LLM/tools and a WorkingMemory.

    Accepts an optional `recorder` kwarg (AsyncMock or real EpisodicRecorder)
    that will be passed in as `episodic_recorder`. The returned agent has its
    `_provider.chat` stubbed to return an empty assistant turn (no tool calls)
    so `handle_message` returns immediately after the user-signal hook fires.
    """

    def _factory(*, recorder=None, signal_detector=None, episodic_store=None):
        registry = ToolRegistry()
        registry.register(_mem_test_tool)

        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=LLMResponse(
                content="ok",
                tool_calls=[],
                usage=TokenUsage(input_tokens=1, output_tokens=1),
                stop_reason="end_turn",
            )
        )

        guard = SafetyGuard()
        memory = WorkingMemory()

        return CoreAgent(
            provider=provider,
            tool_registry=registry,
            safety_guard=guard,
            working_memory=memory,
            signal_detector=signal_detector or SignalDetector(),
            episodic_recorder=recorder,
            episodic_store=episodic_store,
        )

    return _factory


@pytest.fixture
def tool_executor_factory():
    """Build a ToolExecutor with a stub registry for memory-recall tests.

    Registry includes:
      * ``echo`` — returns f"echoed: {x}" with success=True
      * ``boom`` — always raises (forces TOOL_FAILED branch)
      * ``aws_vpc_create`` — returns a fixed success string

    Accepts kwargs ``store`` / ``recorder`` / ``signal_detector`` so tests
    can supply AsyncMocks. Other ToolExecutor kwargs are left at defaults.
    """

    def _factory(*, store=None, recorder=None, signal_detector=None):
        registry = ToolRegistry()

        @tool(description="Echo input")
        async def echo(x: str = "") -> str:
            return f"echoed: {x}"

        @tool(description="Always fails")
        async def boom() -> str:
            raise RuntimeError("boom-failure")

        @tool(description="Create a VPC")
        async def aws_vpc_create(region: str = "") -> str:
            return f"vpc created in {region}"

        registry.register(echo)
        registry.register(boom)
        registry.register(aws_vpc_create)

        guard = SafetyGuard()

        return ToolExecutor(
            tool_registry=registry,
            safety_guard=guard,
            tool_timeout=10,
            episodic_store=store,
            episodic_recorder=recorder,
            signal_detector=signal_detector,
        )

    return _factory
