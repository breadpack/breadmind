"""TierProviderPool: manages per-difficulty LLM provider instances."""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from breadmind.llm.base import LLMProvider

if TYPE_CHECKING:
    from breadmind.config import LLMConfig, ModelTierEntry

logger = logging.getLogger(__name__)

_VALID_TIERS = ("low", "medium", "high")


class TierProviderPool:
    """Routes task difficulty levels to the appropriate LLM provider + model.

    - If a tier has no provider configured, falls back to the default.
    - If a tier uses the same provider as default, returns the default
      instance with a model override (avoids redundant connections).
    - Different-provider tiers get their own cached instance.
    """

    def __init__(
        self, default_provider: LLMProvider, config: LLMConfig,
    ) -> None:
        self._default = default_provider
        self._config = config
        self._cache: dict[tuple[str, str], LLMProvider] = {}

    def get_provider_for_difficulty(
        self, difficulty: str,
    ) -> tuple[LLMProvider, str | None]:
        """Return (provider_instance, model_override_or_None) for a difficulty."""
        tier = self._get_tier(difficulty)
        if not tier or not tier.provider:
            return (self._default, None)

        if tier.provider == self._config.default_provider:
            # Same provider — use model override only
            return (self._default, tier.model or None)

        # Different provider — get or create cached instance
        key = (tier.provider, tier.model)
        if key not in self._cache:
            instance = self._create_provider_for_tier(tier)
            if instance is None:
                logger.warning(
                    "Failed to create provider for tier %s (%s/%s), using default",
                    difficulty, tier.provider, tier.model,
                )
                return (self._default, None)
            self._cache[key] = instance
        return (self._cache[key], tier.model or None)

    def update_config(self, config: LLMConfig) -> None:
        """Hot-swap: update config and clear provider cache."""
        self._config = config
        self._close_cached()
        self._cache.clear()

    def update_default_provider(self, provider: LLMProvider) -> None:
        """Replace the default provider (e.g. after runtime provider switch)."""
        self._default = provider

    def get_tier_status(self) -> dict:
        """Return current tier configuration for API/debugging."""
        result: dict[str, dict] = {}
        for level in _VALID_TIERS:
            tier = self._get_tier(level)
            if tier and tier.provider:
                result[level] = {"provider": tier.provider, "model": tier.model}
            else:
                result[level] = {
                    "provider": self._config.default_provider,
                    "model": self._config.default_model,
                    "inherited": True,
                }
        return result

    # --- Private ---

    def _get_tier(self, difficulty: str) -> ModelTierEntry | None:
        return getattr(self._config, f"tier_{difficulty}", None)

    def _create_provider_for_tier(self, tier: ModelTierEntry) -> LLMProvider | None:
        from breadmind.llm.factory import get_registered_providers

        registry = get_registered_providers()
        info = registry.get(tier.provider)
        if info is None:
            logger.error("Unknown provider '%s' in tier config", tier.provider)
            return None

        try:
            if info.env_key:
                raw_key = os.environ.get(info.env_key, "")
                if not raw_key:
                    logger.error(
                        "%s not set for tier provider '%s'",
                        info.env_key, tier.provider,
                    )
                    return None
                keys = [k.strip() for k in raw_key.split(",") if k.strip()]
                if len(keys) > 1:
                    return info.cls(
                        api_key=keys[0],
                        default_model=tier.model or None,
                        api_keys=keys,
                    )
                return info.cls(api_key=keys[0], default_model=tier.model or None)
            return info.cls()
        except Exception as e:
            logger.error("Failed to create tier provider '%s': %s", tier.provider, e)
            return None

    def _close_cached(self) -> None:
        """Best-effort close of cached providers."""
        import asyncio
        for provider in self._cache.values():
            try:
                coro = provider.close()
                if asyncio.iscoroutine(coro):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(coro)
                    except RuntimeError:
                        pass
            except Exception:
                pass
