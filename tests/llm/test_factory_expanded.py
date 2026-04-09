"""Tests for expanded factory registration."""

from __future__ import annotations

import pytest

from breadmind.llm.factory import (
    get_registered_providers,
    get_provider_options,
    get_valid_provider_names,
    get_env_key_to_provider_map,
)


class TestProviderRegistration:
    """Verify all providers are registered correctly."""

    def test_core_providers_registered(self):
        providers = get_registered_providers()
        for name in ("gemini", "claude", "grok", "ollama"):
            assert name in providers, f"{name} not registered"

    def test_openai_compat_providers_registered(self):
        providers = get_registered_providers()
        for name in ("openai", "deepseek", "openrouter", "mistral",
                      "together", "groq", "azure_openai"):
            assert name in providers, f"{name} not registered"

    def test_minimum_provider_count(self):
        """We should have at least 11 providers (4 core + 7 openai-compat)."""
        providers = get_registered_providers()
        assert len(providers) >= 11

    def test_provider_info_fields(self):
        providers = get_registered_providers()
        for name, info in providers.items():
            assert info.name == name
            assert info.display_name, f"{name} missing display_name"
            assert isinstance(info.models, list)
            assert isinstance(info.free_tier, bool)


class TestProviderOptions:
    def test_options_exclude_cli(self):
        options = get_provider_options()
        ids = [o["id"] for o in options]
        assert "cli" not in ids

    def test_options_have_required_fields(self):
        options = get_provider_options()
        for opt in options:
            assert "id" in opt
            assert "name" in opt
            assert "models" in opt


class TestValidProviderNames:
    def test_includes_cli(self):
        names = get_valid_provider_names()
        assert "cli" in names

    def test_includes_all_registered(self):
        names = get_valid_provider_names()
        providers = get_registered_providers()
        for name in providers:
            assert name in names


class TestEnvKeyMapping:
    def test_env_keys_mapped(self):
        mapping = get_env_key_to_provider_map()
        assert mapping.get("OPENAI_API_KEY") == "openai"
        assert mapping.get("ANTHROPIC_API_KEY") == "claude"
        assert mapping.get("DEEPSEEK_API_KEY") == "deepseek"
        assert mapping.get("GROQ_API_KEY") == "groq"

    def test_ollama_has_no_env_key(self):
        mapping = get_env_key_to_provider_map()
        # Ollama doesn't require an API key
        assert "ollama" not in mapping.values() or \
            all(v != "ollama" for v in mapping.values())


class TestGracefulDegradation:
    def test_bedrock_registration(self):
        """Bedrock should be registered if boto3 is available, skipped otherwise."""
        providers = get_registered_providers()
        # We don't assert presence or absence — just that no error occurs
        if "bedrock" in providers:
            assert providers["bedrock"].display_name == "AWS Bedrock"

    def test_litellm_registration(self):
        """LiteLLM should be registered if importable, skipped otherwise."""
        providers = get_registered_providers()
        if "litellm" in providers:
            assert providers["litellm"].display_name == "LiteLLM (Proxy/Library)"
