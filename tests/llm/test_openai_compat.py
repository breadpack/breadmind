"""Tests for OpenAICompatibleProvider base class."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breadmind.llm.base import (
    LLMMessage,
)
from breadmind.llm.openai_compat import OpenAICompatibleProvider
from .conftest import make_messages, make_tool_result_messages, make_tools


# --- Concrete mock subclass for testing ---

class MockProvider(OpenAICompatibleProvider):
    PROVIDER_NAME = "mock"
    BASE_URL = "https://api.mock.example.com/v1"
    DEFAULT_MODEL = "mock-model-1"


# --- Fixtures ---

@pytest.fixture
def provider():
    with patch("openai.AsyncOpenAI"):
        return MockProvider(api_key="test-key")


# --- Message conversion tests ---

class TestConvertMessages:
    def test_simple_messages(self, provider):
        messages = make_messages()
        result = provider._convert_messages(messages)

        assert len(result) == 3
        assert result[0] == {"role": "system", "content": "You are a helpful assistant."}
        assert result[1] == {"role": "user", "content": "Hello, how are you?"}
        assert result[2] == {"role": "assistant", "content": "I'm doing well!"}

    def test_tool_call_messages(self, provider):
        messages = make_tool_result_messages()
        result = provider._convert_messages(messages)

        assert len(result) == 3
        # User message
        assert result[0]["role"] == "user"
        # Assistant with tool calls
        assert result[1]["role"] == "assistant"
        assert len(result[1]["tool_calls"]) == 1
        tc = result[1]["tool_calls"][0]
        assert tc["id"] == "tc_1"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "get_weather"
        assert json.loads(tc["function"]["arguments"]) == {"city": "Seoul"}
        # Tool result
        assert result[2]["role"] == "tool"
        assert result[2]["tool_call_id"] == "tc_1"

    def test_empty_content_defaults_to_empty_string(self, provider):
        messages = [LLMMessage(role="user", content=None)]
        result = provider._convert_messages(messages)
        assert result[0]["content"] == ""


# --- Tool conversion tests ---

class TestConvertTools:
    def test_convert_tools(self, provider):
        tools = make_tools()
        result = provider._convert_tools(tools)

        assert len(result) == 1
        assert result[0]["type"] == "function"
        func = result[0]["function"]
        assert func["name"] == "get_weather"
        assert func["description"] == "Get weather for a city"
        assert "properties" in func["parameters"]


# --- Response parsing tests ---

class TestParseResponse:
    def test_text_response(self, provider):
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Hello there!"
        mock_choice.message.tool_calls = None
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        result = provider._parse_response(mock_response)
        assert result.content == "Hello there!"
        assert result.tool_calls == []
        assert result.usage.input_tokens == 10
        assert result.usage.output_tokens == 5
        assert result.stop_reason == "end_turn"

    def test_tool_call_response(self, provider):
        mock_tc = MagicMock()
        mock_tc.id = "tc_123"
        mock_tc.function.name = "get_weather"
        mock_tc.function.arguments = '{"city": "Tokyo"}'

        mock_choice = MagicMock()
        mock_choice.message.content = None
        mock_choice.message.tool_calls = [mock_tc]

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 20
        mock_response.usage.completion_tokens = 10

        result = provider._parse_response(mock_response)
        assert result.content is None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "get_weather"
        assert result.tool_calls[0].arguments == {"city": "Tokyo"}
        assert result.stop_reason == "tool_use"

    def test_empty_choices(self, provider):
        mock_response = MagicMock()
        mock_response.choices = []

        result = provider._parse_response(mock_response)
        assert result.content == "No response from mock"
        assert result.stop_reason == "error"

    def test_malformed_tool_call_arguments(self, provider):
        mock_tc = MagicMock()
        mock_tc.id = "tc_bad"
        mock_tc.function.name = "broken_tool"
        mock_tc.function.arguments = "not valid json"

        mock_choice = MagicMock()
        mock_choice.message.content = None
        mock_choice.message.tool_calls = [mock_tc]

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 5
        mock_response.usage.completion_tokens = 5

        result = provider._parse_response(mock_response)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].arguments == {}


# --- Health check tests ---

class TestHealthCheck:
    async def test_health_check_with_key(self, provider):
        provider._client = AsyncMock()
        provider._client.models.list = AsyncMock()
        result = await provider.health_check()
        assert result is True

    async def test_health_check_fallback_on_error(self, provider):
        provider._client = AsyncMock()
        provider._client.models.list = AsyncMock(side_effect=Exception("fail"))
        # Falls back to bool(api_key), which is True
        result = await provider.health_check()
        assert result is True


# --- Provider attributes ---

class TestProviderAttributes:
    def test_model_name(self, provider):
        assert provider.model_name == "mock-model-1"

    def test_custom_model(self):
        with patch("openai.AsyncOpenAI"):
            p = MockProvider(api_key="k", default_model="custom-model")
        assert p.model_name == "custom-model"

    def test_extra_headers(self):
        with patch("openai.AsyncOpenAI"):
            p = MockProvider(api_key="k", extra_headers={"X-Custom": "val"})
        assert p._extra_headers == {"X-Custom": "val"}
