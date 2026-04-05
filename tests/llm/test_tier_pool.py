"""Tests for TierProviderPool — per-difficulty provider routing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from breadmind.config import LLMConfig, ModelTierEntry
from breadmind.llm.tier_pool import TierProviderPool


def _provider_info(mock_cls, env_key):
    """Create a ProviderInfo-like object without conflicting with MagicMock's cls."""
    return SimpleNamespace(cls=mock_cls, env_key=env_key)


def _make_config(
    default_provider="gemini",
    default_model="gemini-2.5-flash",
    tier_low=None,
    tier_medium=None,
    tier_high=None,
) -> LLMConfig:
    return LLMConfig(
        default_provider=default_provider,
        default_model=default_model,
        tier_low=tier_low or ModelTierEntry(),
        tier_medium=tier_medium or ModelTierEntry(),
        tier_high=tier_high or ModelTierEntry(),
    )


class TestTierProviderPoolFallback:
    def test_empty_tiers_returns_default(self):
        default = MagicMock()
        pool = TierProviderPool(default_provider=default, config=_make_config())

        provider, model = pool.get_provider_for_difficulty("low")
        assert provider is default
        assert model is None

    def test_all_difficulties_return_default_when_unconfigured(self):
        default = MagicMock()
        pool = TierProviderPool(default_provider=default, config=_make_config())

        for difficulty in ("low", "medium", "high"):
            provider, model = pool.get_provider_for_difficulty(difficulty)
            assert provider is default
            assert model is None

    def test_unknown_difficulty_returns_default(self):
        default = MagicMock()
        pool = TierProviderPool(default_provider=default, config=_make_config())

        provider, model = pool.get_provider_for_difficulty("unknown")
        assert provider is default
        assert model is None


class TestTierProviderPoolSameProvider:
    def test_same_provider_returns_model_override(self):
        default = MagicMock()
        config = _make_config(
            tier_high=ModelTierEntry(provider="gemini", model="gemini-2.5-pro"),
        )
        pool = TierProviderPool(default_provider=default, config=config)

        provider, model = pool.get_provider_for_difficulty("high")
        assert provider is default
        assert model == "gemini-2.5-pro"

    def test_same_provider_empty_model_returns_none(self):
        default = MagicMock()
        config = _make_config(
            tier_low=ModelTierEntry(provider="gemini", model=""),
        )
        pool = TierProviderPool(default_provider=default, config=config)

        provider, model = pool.get_provider_for_difficulty("low")
        assert provider is default
        assert model is None


class TestTierProviderPoolDifferentProvider:
    @patch("breadmind.llm.factory.get_registered_providers")
    @patch("os.environ.get", return_value="test-api-key")
    def test_different_provider_creates_new_instance(self, mock_env, mock_registry):
        mock_cls = MagicMock()
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        mock_registry.return_value = {
            "claude": _provider_info(mock_cls, "ANTHROPIC_API_KEY"),
        }

        default = MagicMock()
        config = _make_config(
            tier_high=ModelTierEntry(provider="claude", model="claude-opus-4-6"),
        )
        pool = TierProviderPool(default_provider=default, config=config)

        provider, model = pool.get_provider_for_difficulty("high")
        assert provider is mock_instance
        assert model == "claude-opus-4-6"
        mock_cls.assert_called_once_with(api_key="test-api-key", default_model="claude-opus-4-6")

    @patch("breadmind.llm.factory.get_registered_providers")
    @patch("os.environ.get", return_value="test-api-key")
    def test_caches_provider_instance(self, mock_env, mock_registry):
        mock_cls = MagicMock()
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        mock_registry.return_value = {
            "claude": _provider_info(mock_cls, "ANTHROPIC_API_KEY"),
        }

        default = MagicMock()
        config = _make_config(
            tier_high=ModelTierEntry(provider="claude", model="claude-opus-4-6"),
        )
        pool = TierProviderPool(default_provider=default, config=config)

        # Call twice
        pool.get_provider_for_difficulty("high")
        pool.get_provider_for_difficulty("high")

        # Should only create once
        mock_cls.assert_called_once()

    @patch("breadmind.llm.factory.get_registered_providers")
    @patch("os.environ.get", return_value="")
    def test_missing_api_key_falls_back_to_default(self, mock_env, mock_registry):
        mock_registry.return_value = {
            "claude": _provider_info(MagicMock(), "ANTHROPIC_API_KEY"),
        }

        default = MagicMock()
        config = _make_config(
            tier_high=ModelTierEntry(provider="claude", model="claude-opus-4-6"),
        )
        pool = TierProviderPool(default_provider=default, config=config)

        provider, model = pool.get_provider_for_difficulty("high")
        assert provider is default
        assert model is None

    @patch("breadmind.llm.factory.get_registered_providers")
    def test_unknown_provider_falls_back_to_default(self, mock_registry):
        mock_registry.return_value = {}

        default = MagicMock()
        config = _make_config(
            tier_high=ModelTierEntry(provider="nonexistent", model="x"),
        )
        pool = TierProviderPool(default_provider=default, config=config)

        provider, model = pool.get_provider_for_difficulty("high")
        assert provider is default
        assert model is None


class TestTierProviderPoolHotSwap:
    def test_update_config_clears_cache(self):
        default = MagicMock()
        config = _make_config()
        pool = TierProviderPool(default_provider=default, config=config)

        # Simulate cached entry
        pool._cache[("claude", "opus")] = MagicMock()
        assert len(pool._cache) == 1

        new_config = _make_config()
        pool.update_config(new_config)
        assert len(pool._cache) == 0

    def test_update_default_provider(self):
        old_default = MagicMock()
        new_default = MagicMock()
        pool = TierProviderPool(
            default_provider=old_default, config=_make_config(),
        )

        pool.update_default_provider(new_default)
        provider, _ = pool.get_provider_for_difficulty("low")
        assert provider is new_default


class TestTierProviderPoolStatus:
    def test_get_tier_status_unconfigured(self):
        default = MagicMock()
        pool = TierProviderPool(
            default_provider=default,
            config=_make_config(default_provider="gemini", default_model="gemini-2.5-flash"),
        )

        status = pool.get_tier_status()
        for level in ("low", "medium", "high"):
            assert status[level]["provider"] == "gemini"
            assert status[level]["model"] == "gemini-2.5-flash"
            assert status[level]["inherited"] is True

    def test_get_tier_status_configured(self):
        default = MagicMock()
        config = _make_config(
            tier_high=ModelTierEntry(provider="claude", model="claude-opus-4-6"),
        )
        pool = TierProviderPool(default_provider=default, config=config)

        status = pool.get_tier_status()
        assert status["high"]["provider"] == "claude"
        assert status["high"]["model"] == "claude-opus-4-6"
        assert "inherited" not in status["high"]
        assert status["low"]["inherited"] is True
