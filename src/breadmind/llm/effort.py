"""Effort level control for LLM thinking/reasoning budget."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import IntEnum


class EffortLevel(IntEnum):
    LOW = 1       # Minimal thinking, fast responses
    MEDIUM = 2    # Balanced (default)
    HIGH = 3      # Thorough analysis
    MAX = 4       # Maximum reasoning depth (Opus-only)


@dataclass
class EffortConfig:
    """Configuration for effort-based token allocation."""

    level: EffortLevel = EffortLevel.MEDIUM
    think_budget_multiplier: dict[EffortLevel, float] = field(default=None)  # type: ignore[assignment]
    max_tokens_multiplier: dict[EffortLevel, float] = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.think_budget_multiplier is None:
            self.think_budget_multiplier = {
                EffortLevel.LOW: 0.25,
                EffortLevel.MEDIUM: 1.0,
                EffortLevel.HIGH: 2.0,
                EffortLevel.MAX: 4.0,
            }
        if self.max_tokens_multiplier is None:
            self.max_tokens_multiplier = {
                EffortLevel.LOW: 0.5,
                EffortLevel.MEDIUM: 1.0,
                EffortLevel.HIGH: 1.5,
                EffortLevel.MAX: 2.0,
            }


_LEVEL_MAP: dict[str, EffortLevel] = {
    "low": EffortLevel.LOW,
    "medium": EffortLevel.MEDIUM,
    "high": EffortLevel.HIGH,
    "max": EffortLevel.MAX,
}


class EffortManager:
    """Manages thinking effort level for LLM calls.

    Configurable via --effort CLI flag, /effort slash command,
    or BREADMIND_EFFORT_LEVEL env var.
    """

    def __init__(self, config: EffortConfig | None = None) -> None:
        self._config = config or EffortConfig()

    @property
    def level(self) -> EffortLevel:
        return self._config.level

    @level.setter
    def level(self, value: EffortLevel) -> None:
        self._config.level = value

    def get_think_budget(self, base_budget: int = 10_000) -> int:
        """Get adjusted think budget for current effort level."""
        mult = self._config.think_budget_multiplier[self._config.level]
        return int(base_budget * mult)

    def get_max_tokens(self, base_max: int = 8192) -> int:
        """Get adjusted max output tokens."""
        mult = self._config.max_tokens_multiplier[self._config.level]
        return int(base_max * mult)

    def apply_to_kwargs(self, kwargs: dict) -> dict:
        """Modify LLM call kwargs based on effort level.

        Returns a new dict with adjusted ``think_budget`` and ``max_tokens``
        whenever the current level differs from MEDIUM or those keys are
        already present.
        """
        result = dict(kwargs)
        if "think_budget" in result or self._config.level != EffortLevel.MEDIUM:
            base = result.get("think_budget", 10_000)
            result["think_budget"] = self.get_think_budget(base)
        if "max_tokens" in result or self._config.level != EffortLevel.MEDIUM:
            base = result.get("max_tokens", 8192)
            result["max_tokens"] = self.get_max_tokens(base)
        return result

    @classmethod
    def from_env(cls) -> EffortManager:
        """Create from ``BREADMIND_EFFORT_LEVEL`` env var."""
        level_str = os.environ.get("BREADMIND_EFFORT_LEVEL", "medium").lower()
        level = _LEVEL_MAP.get(level_str, EffortLevel.MEDIUM)
        return cls(EffortConfig(level=level))

    @classmethod
    def from_string(cls, s: str) -> EffortManager:
        """Create from string like ``'low'``, ``'medium'``, ``'high'``, ``'max'``."""
        level = _LEVEL_MAP.get(s.lower().strip(), EffortLevel.MEDIUM)
        return cls(EffortConfig(level=level))
