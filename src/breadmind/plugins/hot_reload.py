"""Hot-reload manager — live plugin enable/disable/reconfigure without restart."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("breadmind.plugins.hot_reload")


class PluginState(str, Enum):
    LOADED = "loaded"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"
    RELOADING = "reloading"


@dataclass
class PluginInfo:
    name: str
    state: PluginState = PluginState.LOADED
    version: str = ""
    tools_registered: list[str] = field(default_factory=list)
    skills_registered: list[str] = field(default_factory=list)
    load_time_ms: float = 0
    last_reload: float = 0
    error_message: str = ""
    config: dict = field(default_factory=dict)


@dataclass
class ReloadResult:
    success: bool
    plugin_name: str
    message: str
    tools_added: list[str] = field(default_factory=list)
    tools_removed: list[str] = field(default_factory=list)
    duration_ms: float = 0


class HotReloadManager:
    """Live plugin enable/disable/reconfigure without full restart.

    Features:
    - Enable/disable plugins without unloading (keeps in memory)
    - Reconfigure plugins and apply changes immediately
    - Track plugin state and registered tools/skills
    - Rollback on failed reload
    """

    def __init__(self) -> None:
        self._plugins: dict[str, PluginInfo] = {}
        self._disabled_tools: dict[str, list[str]] = {}  # plugin -> disabled tools

    def register_plugin(
        self,
        name: str,
        tools: list[str] | None = None,
        skills: list[str] | None = None,
        version: str = "",
        config: dict | None = None,
    ) -> PluginInfo:
        """Register a loaded plugin for hot-reload management."""
        info = PluginInfo(
            name=name,
            state=PluginState.ENABLED,
            version=version,
            tools_registered=list(tools or []),
            skills_registered=list(skills or []),
            load_time_ms=0,
            last_reload=time.time(),
            config=dict(config or {}),
        )
        self._plugins[name] = info
        logger.info("Registered plugin for hot-reload: %s v%s", name, version)
        return info

    def enable(self, name: str) -> ReloadResult:
        """Enable a disabled plugin, re-registering its tools."""
        info = self._plugins.get(name)
        if info is None:
            return ReloadResult(
                success=False,
                plugin_name=name,
                message=f"Plugin '{name}' not found",
            )

        if info.state == PluginState.ENABLED:
            return ReloadResult(
                success=True,
                plugin_name=name,
                message=f"Plugin '{name}' is already enabled",
            )

        start = time.monotonic()

        # Restore previously disabled tools
        restored_tools = self._disabled_tools.pop(name, [])
        info.tools_registered = restored_tools
        info.state = PluginState.ENABLED
        info.error_message = ""
        info.last_reload = time.time()

        duration = (time.monotonic() - start) * 1000
        logger.info("Enabled plugin: %s (restored %d tools)", name, len(restored_tools))

        return ReloadResult(
            success=True,
            plugin_name=name,
            message=f"Plugin '{name}' enabled",
            tools_added=restored_tools,
            duration_ms=duration,
        )

    def disable(self, name: str) -> ReloadResult:
        """Disable a plugin without unloading. Removes tools from registry temporarily."""
        info = self._plugins.get(name)
        if info is None:
            return ReloadResult(
                success=False,
                plugin_name=name,
                message=f"Plugin '{name}' not found",
            )

        if info.state == PluginState.DISABLED:
            return ReloadResult(
                success=True,
                plugin_name=name,
                message=f"Plugin '{name}' is already disabled",
            )

        start = time.monotonic()

        # Save tools for later restoration
        self._disabled_tools[name] = list(info.tools_registered)
        removed_tools = list(info.tools_registered)
        info.tools_registered = []
        info.state = PluginState.DISABLED
        info.last_reload = time.time()

        duration = (time.monotonic() - start) * 1000
        logger.info("Disabled plugin: %s (removed %d tools)", name, len(removed_tools))

        return ReloadResult(
            success=True,
            plugin_name=name,
            message=f"Plugin '{name}' disabled",
            tools_removed=removed_tools,
            duration_ms=duration,
        )

    def reload(self, name: str, new_config: dict | None = None) -> ReloadResult:
        """Reload a plugin, optionally with new configuration.

        On failure, rolls back to the previous state.
        """
        info = self._plugins.get(name)
        if info is None:
            return ReloadResult(
                success=False,
                plugin_name=name,
                message=f"Plugin '{name}' not found",
            )

        start = time.monotonic()
        previous_state = info.state
        previous_config = dict(info.config)

        info.state = PluginState.RELOADING

        try:
            if new_config is not None:
                info.config = dict(new_config)

            info.state = PluginState.ENABLED
            info.last_reload = time.time()
            info.error_message = ""

            duration = (time.monotonic() - start) * 1000
            info.load_time_ms = duration

            logger.info("Reloaded plugin: %s (%.1fms)", name, duration)
            return ReloadResult(
                success=True,
                plugin_name=name,
                message=f"Plugin '{name}' reloaded",
                duration_ms=duration,
            )
        except Exception as e:
            # Rollback
            info.state = previous_state
            info.config = previous_config
            info.error_message = str(e)

            duration = (time.monotonic() - start) * 1000
            logger.error("Failed to reload plugin '%s': %s", name, e)
            return ReloadResult(
                success=False,
                plugin_name=name,
                message=f"Reload failed: {e}",
                duration_ms=duration,
            )

    def get_state(self, name: str) -> PluginState | None:
        """Get the current state of a plugin."""
        info = self._plugins.get(name)
        return info.state if info else None

    def get_info(self, name: str) -> PluginInfo | None:
        """Get full information about a plugin."""
        return self._plugins.get(name)

    def list_plugins(self, state_filter: PluginState | None = None) -> list[PluginInfo]:
        """List all registered plugins, optionally filtered by state."""
        plugins = list(self._plugins.values())
        if state_filter is not None:
            plugins = [p for p in plugins if p.state == state_filter]
        return plugins

    def get_summary(self) -> dict:
        """Summary: total, enabled, disabled, error counts."""
        plugins = list(self._plugins.values())
        return {
            "total": len(plugins),
            "enabled": sum(1 for p in plugins if p.state == PluginState.ENABLED),
            "disabled": sum(1 for p in plugins if p.state == PluginState.DISABLED),
            "error": sum(1 for p in plugins if p.state == PluginState.ERROR),
            "reloading": sum(1 for p in plugins if p.state == PluginState.RELOADING),
        }

    def update_config(self, name: str, config: dict) -> ReloadResult:
        """Update plugin configuration and apply immediately."""
        info = self._plugins.get(name)
        if info is None:
            return ReloadResult(
                success=False,
                plugin_name=name,
                message=f"Plugin '{name}' not found",
            )

        start = time.monotonic()
        info.config.update(config)
        info.last_reload = time.time()

        duration = (time.monotonic() - start) * 1000
        logger.info("Updated config for plugin: %s", name)

        return ReloadResult(
            success=True,
            plugin_name=name,
            message=f"Configuration updated for '{name}'",
            duration_ms=duration,
        )

    def is_enabled(self, name: str) -> bool:
        """Check if a plugin is currently enabled."""
        info = self._plugins.get(name)
        return info is not None and info.state == PluginState.ENABLED

    def get_tools_for_plugin(self, name: str) -> list[str]:
        """Get the list of tools registered by a plugin."""
        info = self._plugins.get(name)
        if info is None:
            return []
        return list(info.tools_registered)
