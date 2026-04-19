"""Tests for create_provider() — provider instantiation via config.

Exercises the generic builder pipeline: each provider declares its own
builder (or falls through to the default builder that forwards per-provider
settings as kwargs). The factory itself has no provider-specific branching.
"""

from __future__ import annotations

from typing import Any

import pytest

from breadmind.config import AppConfig
from breadmind.llm import factory
from breadmind.llm.base import LLMProvider
from breadmind.llm.factory import create_provider, register_provider
from breadmind.llm.ollama import OllamaProvider


def _make_config(**llm_overrides) -> AppConfig:
    config = AppConfig()
    for key, value in llm_overrides.items():
        setattr(config.llm, key, value)
    return config


class TestOllamaFromConfig:
    """Ollama reads base_url + default_model from config.llm.providers['ollama']."""

    def test_default_ollama_uses_localhost(self):
        config = _make_config(default_provider="ollama", default_model="llama3")
        provider = create_provider(config)
        assert isinstance(provider, OllamaProvider)
        assert provider._base_url == "http://localhost:11434"
        assert provider.model_name == "llama3"

    def test_provider_settings_override_base_url(self):
        config = _make_config(
            default_provider="ollama",
            default_model="gemma4-e2b-lite",
            providers={"ollama": {"base_url": "http://10.0.0.109:11434"}},
        )
        provider = create_provider(config)
        assert isinstance(provider, OllamaProvider)
        assert provider._base_url == "http://10.0.0.109:11434"
        assert provider.model_name == "gemma4-e2b-lite"

    def test_trailing_slash_stripped(self):
        config = _make_config(
            default_provider="ollama",
            providers={"ollama": {"base_url": "http://10.0.0.109:11434/"}},
        )
        provider = create_provider(config)
        assert provider._base_url == "http://10.0.0.109:11434"

    def test_per_provider_default_model_override(self):
        """providers['ollama']['default_model'] wins over config.llm.default_model."""
        config = _make_config(
            default_provider="ollama",
            default_model="llama3",
            providers={"ollama": {"default_model": "gemma4-e2b-lite"}},
        )
        provider = create_provider(config)
        assert provider.model_name == "gemma4-e2b-lite"


class TestFallbackBehavior:
    def test_missing_api_key_falls_back_to_configured_provider(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        config = _make_config(
            default_provider="claude",
            default_model="claude-sonnet-4-6",
            fallback_provider="ollama",
            providers={"ollama": {"base_url": "http://10.0.0.109:11434"}},
        )
        provider = create_provider(config)
        assert isinstance(provider, OllamaProvider)
        assert provider._base_url == "http://10.0.0.109:11434"
        # On fallback, Ollama uses its own default model (not the claude one).
        assert provider.model_name == "llama3"

    def test_unknown_provider_falls_back(self):
        config = _make_config(
            default_provider="nonexistent_provider",
            fallback_provider="ollama",
            providers={"ollama": {"base_url": "http://10.0.0.109:11434"}},
        )
        provider = create_provider(config)
        assert isinstance(provider, OllamaProvider)
        assert provider._base_url == "http://10.0.0.109:11434"

    def test_self_fallback_does_not_recurse(self, monkeypatch):
        """When fallback_provider == default_provider, no infinite recursion.
        The factory hands off to the provider's builder, which either succeeds
        or raises a construction error — never loops."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        config = _make_config(
            default_provider="claude",
            fallback_provider="claude",  # self-fallback
        )
        # Without API key and no valid fallback, ClaudeProvider construction
        # fails with TypeError — proving we didn't recurse.
        with pytest.raises((TypeError, ValueError, RuntimeError)):
            create_provider(config)

    def test_no_fallback_for_unknown_provider_raises(self):
        config = _make_config(
            default_provider="nonexistent",
            fallback_provider="",
        )
        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider(config)


class TestNonOllamaProvidersUnaffected:
    def test_claude_gets_api_key_and_default_model(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-key")
        config = _make_config(
            default_provider="claude",
            default_model="claude-sonnet-4-6",
        )
        provider = create_provider(config)
        assert not isinstance(provider, OllamaProvider)
        assert provider.model_name == "claude-sonnet-4-6"


class TestGenericProviderSettingsInjection:
    """Per-provider settings should be forwarded as kwargs by the default builder —
    no factory change needed to support a new constructor parameter."""

    def test_settings_forwarded_to_provider_class(self, monkeypatch):
        """Register a dummy provider with a builder that echoes settings."""
        captured: dict[str, Any] = {}

        class DummyProvider(LLMProvider):
            def __init__(self, api_key: str, default_model: str, site_url: str | None = None,
                         custom_flag: bool = False):
                captured["api_key"] = api_key
                captured["default_model"] = default_model
                captured["site_url"] = site_url
                captured["custom_flag"] = custom_flag

            async def chat(self, messages, tools=None, model=None, think_budget=None):
                raise NotImplementedError

            async def chat_stream(self, messages, tools=None, model=None):
                raise NotImplementedError

            async def health_check(self):
                return True

            async def close(self):
                pass

            @property
            def model_name(self) -> str:
                return captured["default_model"]

        register_provider(
            "dummy_test_provider", DummyProvider, "DUMMY_TEST_KEY",
            display_name="Dummy",
        )
        try:
            monkeypatch.setenv("DUMMY_TEST_KEY", "abc")
            config = _make_config(
                default_provider="dummy_test_provider",
                default_model="dummy-model",
                providers={"dummy_test_provider": {
                    "site_url": "https://example.com",
                    "custom_flag": True,
                }},
            )
            create_provider(config)
            assert captured == {
                "api_key": "abc",
                "default_model": "dummy-model",
                "site_url": "https://example.com",
                "custom_flag": True,
            }
        finally:
            factory._PROVIDER_REGISTRY.pop("dummy_test_provider", None)
