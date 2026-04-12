"""Bare mode for reproducible CI/headless runs.

``--bare`` disables user config, auto-memory, plugins, and rules so
that runs are reproducible across environments.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BareConfig:
    """Configuration for bare mode execution."""

    skip_user_config: bool = True
    skip_auto_memory: bool = True
    skip_plugins: bool = True
    skip_rules: bool = True
    minimal_prompt: bool = True
    allowed_tools: list[str] | None = None


class BareMode:
    """Manages bare mode for reproducible CI/headless runs.

    When enabled:
    - User config files (~/.breadmind/) are not loaded
    - Auto-memory is disabled
    - Plugins are not loaded
    - Only essential system prompt is used
    - Tool access can be restricted via ``--allowedTools``
    """

    def __init__(
        self,
        enabled: bool = False,
        config: BareConfig | None = None,
    ) -> None:
        self._enabled = enabled
        self._config = config or BareConfig()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def config(self) -> BareConfig:
        return self._config

    def should_load_user_config(self) -> bool:
        return not self._enabled or not self._config.skip_user_config

    def should_load_memory(self) -> bool:
        return not self._enabled or not self._config.skip_auto_memory

    def should_load_plugins(self) -> bool:
        return not self._enabled or not self._config.skip_plugins

    def should_load_rules(self) -> bool:
        return not self._enabled or not self._config.skip_rules

    def should_use_minimal_prompt(self) -> bool:
        """Return True when only the minimal system prompt should be used."""
        return self._enabled and self._config.minimal_prompt

    def filter_tools(self, tools: list[str]) -> list[str]:
        """Filter tool list if ``allowed_tools`` is configured."""
        if not self._enabled or self._config.allowed_tools is None:
            return tools
        allowed = set(self._config.allowed_tools)
        return [t for t in tools if t in allowed]
