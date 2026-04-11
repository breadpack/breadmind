"""Shared fixtures for LLM tests."""

from __future__ import annotations

from breadmind.llm.base import LLMMessage, ToolCall, ToolDefinition


def make_messages() -> list[LLMMessage]:
    """Create a sample message list for testing."""
    return [
        LLMMessage(role="system", content="You are a helpful assistant."),
        LLMMessage(role="user", content="Hello, how are you?"),
        LLMMessage(role="assistant", content="I'm doing well!"),
    ]


def make_tool_result_messages() -> list[LLMMessage]:
    """Create messages with tool calls and tool results."""
    return [
        LLMMessage(role="user", content="What's the weather?"),
        LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(id="tc_1", name="get_weather", arguments={"city": "Seoul"}),
            ],
        ),
        LLMMessage(
            role="tool",
            content='{"temp": 22, "condition": "sunny"}',
            tool_call_id="tc_1",
        ),
    ]


def make_tools() -> list[ToolDefinition]:
    """Create sample tool definitions."""
    return [
        ToolDefinition(
            name="get_weather",
            description="Get weather for a city",
            parameters={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                },
                "required": ["city"],
            },
        ),
    ]
