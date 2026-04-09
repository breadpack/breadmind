"""Tests for concrete provider subclasses."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from breadmind.llm.openai_provider import OpenAIProvider
from breadmind.llm.deepseek import DeepSeekProvider
from breadmind.llm.openrouter import OpenRouterProvider
from breadmind.llm.mistral import MistralProvider
from breadmind.llm.together import TogetherProvider
from breadmind.llm.groq_provider import GroqProvider
from breadmind.llm.azure_openai import AzureOpenAIProvider
from breadmind.llm.grok import GrokProvider


@pytest.fixture(autouse=True)
def mock_openai_client():
    with patch("openai.AsyncOpenAI"), patch("openai.AsyncAzureOpenAI"):
        yield


class TestOpenAIProvider:
    def test_attributes(self):
        p = OpenAIProvider(api_key="sk-test")
        assert p.PROVIDER_NAME == "openai"
        assert p.BASE_URL == "https://api.openai.com/v1"
        assert p.model_name == "gpt-4o"

    def test_custom_model(self):
        p = OpenAIProvider(api_key="sk-test", default_model="gpt-4o-mini")
        assert p.model_name == "gpt-4o-mini"


class TestDeepSeekProvider:
    def test_attributes(self):
        p = DeepSeekProvider(api_key="sk-test")
        assert p.PROVIDER_NAME == "deepseek"
        assert p.BASE_URL == "https://api.deepseek.com/v1"
        assert p.model_name == "deepseek-chat"

    def test_extra_kwargs_for_r1(self):
        p = DeepSeekProvider(api_key="sk-test")
        kwargs = {"model": "deepseek-r1", "max_tokens": 4096, "messages": []}
        result = p._extra_chat_kwargs(kwargs)
        assert result["max_tokens"] == 8192

    def test_extra_kwargs_normal_model(self):
        p = DeepSeekProvider(api_key="sk-test")
        kwargs = {"model": "deepseek-chat", "max_tokens": 4096, "messages": []}
        result = p._extra_chat_kwargs(kwargs)
        assert result["max_tokens"] == 4096


class TestOpenRouterProvider:
    def test_attributes(self):
        p = OpenRouterProvider(api_key="sk-test")
        assert p.PROVIDER_NAME == "openrouter"
        assert p.BASE_URL == "https://openrouter.ai/api/v1"

    def test_extra_headers(self):
        p = OpenRouterProvider(api_key="sk-test", app_title="MyApp")
        headers = p._extra_default_headers()
        assert headers["X-Title"] == "MyApp"

    def test_site_url_header(self):
        p = OpenRouterProvider(
            api_key="sk-test", site_url="https://example.com"
        )
        headers = p._extra_default_headers()
        assert headers["HTTP-Referer"] == "https://example.com"


class TestMistralProvider:
    def test_attributes(self):
        p = MistralProvider(api_key="sk-test")
        assert p.PROVIDER_NAME == "mistral"
        assert p.BASE_URL == "https://api.mistral.ai/v1"
        assert p.model_name == "mistral-large-latest"


class TestTogetherProvider:
    def test_attributes(self):
        p = TogetherProvider(api_key="sk-test")
        assert p.PROVIDER_NAME == "together"
        assert p.BASE_URL == "https://api.together.xyz/v1"


class TestGroqProvider:
    def test_attributes(self):
        p = GroqProvider(api_key="sk-test")
        assert p.PROVIDER_NAME == "groq"
        assert p.BASE_URL == "https://api.groq.com/openai/v1"
        assert p.model_name == "llama-3.3-70b-versatile"


class TestGrokProvider:
    def test_attributes(self):
        p = GrokProvider(api_key="sk-test")
        assert p.PROVIDER_NAME == "grok"
        assert p.BASE_URL == "https://api.x.ai/v1"
        assert p.model_name == "grok-3"

    async def test_health_check(self):
        p = GrokProvider(api_key="sk-test")
        assert await p.health_check() is True

    async def test_health_check_empty_key(self):
        p = GrokProvider(api_key="")
        assert await p.health_check() is False


class TestAzureOpenAIProvider:
    def test_attributes(self):
        p = AzureOpenAIProvider(
            api_key="sk-test",
            azure_endpoint="https://my-resource.openai.azure.com",
        )
        assert p.PROVIDER_NAME == "azure_openai"
        assert p.model_name == "gpt-4o"

    async def test_health_check(self):
        p = AzureOpenAIProvider(
            api_key="sk-test",
            azure_endpoint="https://my-resource.openai.azure.com",
        )
        assert await p.health_check() is True

    async def test_health_check_no_endpoint(self):
        p = AzureOpenAIProvider(api_key="sk-test", azure_endpoint="")
        assert await p.health_check() is False
