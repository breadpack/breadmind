"""Reusable factory functions for creating test mocks and data objects.

Import these directly in test files::

    from tests.factories import make_mock_provider, make_text_response
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from breadmind.core.protocols import (
    AgentContext,
    LLMResponse,
    PromptBlock,
    TokenUsage,
    ToolCallRequest,
    ToolResult,
)


# ---------------------------------------------------------------------------
# LLMResponse factories
# ---------------------------------------------------------------------------


def make_text_response(
    content: str = "OK",
    usage: TokenUsage | None = None,
) -> LLMResponse:
    """Create an LLMResponse with text content and no tool calls."""
    return LLMResponse(
        content=content,
        tool_calls=[],
        usage=usage or TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )


def make_tool_call_response(
    calls: list[tuple[str, str, dict]],
    usage: TokenUsage | None = None,
) -> LLMResponse:
    """Create an LLMResponse that requests tool calls.

    Each element in *calls* is ``(id, name, arguments)``.
    """
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallRequest(id=tc_id, name=name, arguments=args)
            for tc_id, name, args in calls
        ],
        usage=usage or TokenUsage(input_tokens=50, output_tokens=20),
        stop_reason="tool_use",
    )


def make_tool_result(output: str = "OK", success: bool = True) -> ToolResult:
    """Create a ToolResult."""
    return ToolResult(success=success, output=output)


# ---------------------------------------------------------------------------
# Mock builder functions
# ---------------------------------------------------------------------------


def make_mock_provider(
    responses: list[LLMResponse] | None = None,
) -> AsyncMock:
    """Return an AsyncMock that satisfies ProviderProtocol.

    *responses* are fed to ``chat`` via ``side_effect``. If omitted a single
    text response is returned.
    """
    provider = AsyncMock()
    if responses is None:
        responses = [make_text_response()]
    provider.chat = AsyncMock(side_effect=list(responses))

    async def _stream(*_a, **_kw):  # noqa: ANN
        resp = await provider.chat(*_a, **_kw)
        if resp.content:
            yield resp.content

    provider.chat_stream = _stream
    return provider


def make_mock_prompt_builder(
    blocks: list[PromptBlock] | None = None,
) -> MagicMock:
    """Return a MagicMock prompt builder.

    ``build()`` returns the given *blocks* or a default identity block.
    """
    builder = MagicMock()
    if blocks is None:
        blocks = [
            PromptBlock(
                section="identity",
                content="You are BreadMind.",
                cacheable=True,
                priority=1,
            ),
        ]
    builder.build.return_value = list(blocks)
    return builder


def make_mock_tool_registry(
    schemas: list | None = None,
    results: list[ToolResult] | None = None,
) -> MagicMock:
    """Return a MagicMock tool registry.

    ``get_schemas()`` returns *schemas* (default empty list).
    ``execute()`` returns the first element of *results* (default ``ToolResult(success=True, output="OK")``).
    ``execute_batch()`` returns *results*.
    """
    registry = MagicMock()
    registry.get_schemas.return_value = schemas if schemas is not None else []
    default_result = make_tool_result()
    single = (results[0] if results else default_result)
    registry.execute = AsyncMock(return_value=single)
    registry.execute_batch = AsyncMock(
        return_value=list(results) if results else [default_result],
    )
    return registry


def make_agent_context(
    user: str = "test_user",
    channel: str = "test",
    session_id: str | None = None,
) -> AgentContext:
    """Create an AgentContext with sensible defaults."""
    return AgentContext(
        user=user,
        channel=channel,
        session_id=session_id or uuid.uuid4().hex[:8],
    )
