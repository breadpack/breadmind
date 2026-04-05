"""Shared test fixtures for BreadMind tests.

Factory functions live in ``tests.factories`` and are re-exported here so
that both fixtures and test files can use them.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from breadmind.core.protocols import AgentContext

# Re-export factory functions so they are discoverable from conftest
from tests.factories import (  # noqa: F401
    make_agent_context,
    make_mock_prompt_builder,
    make_mock_provider,
    make_mock_tool_registry,
    make_text_response,
    make_tool_call_response,
    make_tool_result,
)


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def safety_config():
    """Legacy safety config dict (kept for backward compatibility)."""
    return {
        "blacklist": {
            "test": ["dangerous_action"],
        },
        "require_approval": ["needs_approval"],
    }


@pytest.fixture
def mock_provider() -> AsyncMock:
    """Provider that returns a single default text response."""
    return make_mock_provider()


@pytest.fixture
def mock_prompt_builder() -> MagicMock:
    """Prompt builder that returns a single identity block."""
    return make_mock_prompt_builder()


@pytest.fixture
def mock_tool_registry() -> MagicMock:
    """Tool registry with empty schemas."""
    return make_mock_tool_registry()


@pytest.fixture
def agent_context() -> AgentContext:
    """Default AgentContext for tests."""
    return make_agent_context()


@pytest.fixture
def safety_guard():
    """SafetyGuard in fully autonomous mode."""
    from breadmind.plugins.builtin.safety.guard import SafetyGuard
    return SafetyGuard(autonomy="auto")


@pytest.fixture
def message_loop_agent(
    mock_provider,
    mock_prompt_builder,
    mock_tool_registry,
    safety_guard,
):
    """MessageLoopAgent wired with default mock collaborators."""
    from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent
    return MessageLoopAgent(
        provider=mock_provider,
        prompt_builder=mock_prompt_builder,
        tool_registry=mock_tool_registry,
        safety_guard=safety_guard,
        max_turns=5,
    )
