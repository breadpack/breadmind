"""Fast mode: same model, optimized for speed over quality."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class FastModeConfig:
    """Configuration for fast mode inference."""
    enabled: bool = False
    max_tokens_override: int | None = None  # lower max_tokens for faster response
    temperature_override: float | None = None  # lower temp for more deterministic
    skip_thinking: bool = True  # skip extended thinking if supported
    prefer_cache: bool = True  # prefer cached responses

class FastModeManager:
    """Manages fast mode toggle for LLM providers."""

    def __init__(self) -> None:
        self._config = FastModeConfig()

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def toggle(self) -> bool:
        """Toggle fast mode. Returns new state."""
        self._config.enabled = not self._config.enabled
        return self._config.enabled

    def enable(self) -> None:
        self._config.enabled = True

    def disable(self) -> None:
        self._config.enabled = False

    def apply_to_kwargs(self, kwargs: dict) -> dict:
        """Apply fast mode settings to LLM call kwargs."""
        if not self._config.enabled:
            return kwargs

        result = dict(kwargs)
        if self._config.max_tokens_override:
            result["max_tokens"] = min(
                result.get("max_tokens", 4096),
                self._config.max_tokens_override,
            )
        if self._config.temperature_override is not None:
            result["temperature"] = self._config.temperature_override
        if self._config.skip_thinking:
            result.pop("think_budget", None)
        return result

    def get_status(self) -> dict:
        return {
            "enabled": self._config.enabled,
            "skip_thinking": self._config.skip_thinking,
            "prefer_cache": self._config.prefer_cache,
        }
