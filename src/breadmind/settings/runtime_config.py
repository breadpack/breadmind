"""Holds the live copy of runtime configuration keys that CoreAgent and its
collaborators read through indirection so hot reload is transparent."""
from __future__ import annotations

import logging
from typing import Any

from breadmind.settings.reload_registry import SettingsReloadRegistry

_KEYS = (
    "retry_config",
    "limits_config",
    "polling_config",
    "agent_timeouts",
    "system_timeouts",
    "logging_config",
    "memory_gc_config",
)


class RuntimeConfigHolder:
    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._state: dict[str, Any] = dict(initial or {})

    def get(self, key: str) -> Any:
        return self._state.get(key)

    def register(self, registry: SettingsReloadRegistry) -> None:
        for key in _KEYS:
            registry.register(key, self._make_reloader(key))

    def _make_reloader(self, key: str):
        async def _reload(ctx: dict[str, Any]) -> None:
            self._state[key] = ctx["new"]
            if key == "logging_config":
                self._apply_logging(ctx["new"] or {})
        return _reload

    @staticmethod
    def _apply_logging(cfg: dict[str, Any]) -> None:
        level_name = str(cfg.get("level", "INFO")).upper()
        level = getattr(logging, level_name, logging.INFO)
        logging.getLogger().setLevel(level)
