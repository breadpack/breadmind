"""Plugin manager — discovers, loads, and manages all plugins."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from breadmind.core.events import get_event_bus
from breadmind.hooks import HookEvent, HookPayload
from breadmind.plugins.container import ServiceContainer
from breadmind.plugins.loader import LoadedComponents, PluginLoader
from breadmind.plugins.manifest import PluginManifest
from breadmind.plugins.protocol import ToolPlugin
from breadmind.plugins.registry import PluginRegistry

logger = logging.getLogger("breadmind.plugins")


class PluginManager:
    """Manages the full plugin lifecycle: discover, load, register tools, unload."""

    def __init__(
        self,
        plugins_dir: Path,
        tool_registry: Any = None,
        container: ServiceContainer | None = None,
    ):
        self._plugins_dir = plugins_dir
        self._plugins_dir.mkdir(parents=True, exist_ok=True)
        self._registry = PluginRegistry(plugins_dir / "registry.json")
        self._loader = PluginLoader()
        self._tool_registry = tool_registry
        self._container = container or ServiceContainer()
        self._loaded: dict[str, LoadedComponents] = {}
        self._manifests: dict[str, PluginManifest] = {}
        self._markets_config: list[dict] = []

    async def apply_markets(self, markets: list[dict] | None) -> None:
        """Record the new skill-market configuration.

        Full marketplace sync (downloading/installing/removing plugins from
        markets) is a separate feature — this method only updates the stored
        config so the reloader chain has a real target and logs an info
        message indicating that a process restart is required for the full
        effect.
        """
        self._markets_config = list(markets or [])
        logging.getLogger(__name__).info(
            "plugin markets updated (%d entries); full sync requires restart",
            len(self._markets_config),
        )

    def get_markets_config(self) -> list[dict]:
        """Return the most recently applied markets config (for tests / debug)."""
        return list(self._markets_config)

    @property
    def loaded_plugins(self) -> dict[str, LoadedComponents]:
        return dict(self._loaded)

    @property
    def container(self) -> ServiceContainer:
        return self._container

    @container.setter
    def container(self, value: ServiceContainer) -> None:
        self._container = value

    @property
    def tool_registry(self) -> Any:
        return self._tool_registry

    @tool_registry.setter
    def tool_registry(self, value: Any) -> None:
        self._tool_registry = value

    # ── Discovery ────────────────────────────────────────────────────────

    async def discover(self) -> list[PluginManifest]:
        manifests = []
        if not self._plugins_dir.exists():
            return manifests
        for p in self._plugins_dir.iterdir():
            if (p / ".claude-plugin" / "plugin.json").exists():
                try:
                    manifests.append(PluginManifest.from_directory(p))
                except Exception as e:
                    logger.warning("Failed to parse plugin at %s: %s", p, e)
        return manifests

    # ── Loading ──────────────────────────────────────────────────────────

    async def load(self, plugin_name: str) -> LoadedComponents | None:
        plugin_dir = self._plugins_dir / plugin_name
        if not (plugin_dir / ".claude-plugin" / "plugin.json").exists():
            logger.warning("Plugin not found: %s", plugin_name)
            return None
        return await self.load_from_directory(plugin_dir)

    async def load_from_directory(self, plugin_dir: Path) -> LoadedComponents | None:
        try:
            manifest = PluginManifest.from_directory(plugin_dir)
        except Exception as e:
            logger.warning("Failed to load plugin at %s: %s", plugin_dir, e)
            return None

        # Check dependencies (hard failure)
        missing_deps = [dep for dep in manifest.depends_on if dep not in self._loaded]
        if missing_deps:
            logger.warning(
                "Plugin '%s' skipped: missing dependencies %s",
                manifest.name, missing_deps,
            )
            return None

        # Check required services
        missing = [r for r in manifest.requires if not self._container.has(r)]
        if missing:
            logger.warning(
                "Plugin '%s' requires services not available: %s — skipping",
                manifest.name, missing,
            )
            return None

        # Log optional service availability
        if manifest.optional_requires:
            available = [r for r in manifest.optional_requires if self._container.has(r)]
            unavailable = [r for r in manifest.optional_requires if not self._container.has(r)]
            if unavailable:
                logger.debug(
                    "Plugin '%s' optional services: available=%s, missing=%s",
                    manifest.name, available, unavailable,
                )

        components = self._loader.load(manifest)

        # Setup Python-based plugin
        if components.plugin_instance is not None:
            try:
                await components.plugin_instance.setup(self._container)
            except Exception as e:
                logger.error(
                    "Plugin '%s' setup() failed: %s", manifest.name, e,
                )
                return None

            # Register tools from plugin instance
            if self._tool_registry:
                for tool_func in components.plugin_instance.get_tools():
                    try:
                        self._tool_registry.register(tool_func)
                    except Exception as e:
                        logger.warning(
                            "Failed to register tool from plugin '%s': %s",
                            manifest.name, e,
                        )

        # Register coding agents (legacy/declarative)
        try:
            from breadmind.coding.adapters import register_adapter
            for adapter in components.coding_agents:
                register_adapter(adapter.name, adapter)
                logger.info(
                    "Registered coding agent: %s from plugin %s",
                    adapter.name, manifest.name,
                )
        except ImportError:
            pass

        # Register safety declarations
        self._register_safety(manifest)

        self._loaded[manifest.name] = components
        self._manifests[manifest.name] = manifest

        # Update external plugin registry
        await self._registry.add(manifest.name, {
            "version": manifest.version,
            "enabled": True,
            "path": str(plugin_dir),
            "description": manifest.description,
        })

        logger.info(
            "Loaded plugin: %s v%s (priority=%d)",
            manifest.name, manifest.version, manifest.priority,
        )

        await get_event_bus().run_hook_chain(
            HookEvent.PLUGIN_LOADED,
            HookPayload(
                event=HookEvent.PLUGIN_LOADED,
                data={
                    "plugin_name": manifest.name,
                    "version": getattr(manifest, "version", ""),
                    "path": str(plugin_dir),
                },
            ),
        )
        return components

    def _register_safety(self, manifest: PluginManifest) -> None:
        """Merge plugin safety declarations into SafetyGuard."""
        if not self._container.has("safety_guard"):
            return
        guard = self._container.get("safety_guard")
        guard.merge_plugin_safety(manifest.name, {
            "require_approval": manifest.safety.require_approval,
            "blacklist": manifest.safety.blacklist,
        })

    # ── Bulk loading ─────────────────────────────────────────────────────

    async def load_all(self) -> None:
        """Load all discovered plugins in priority order."""
        manifests = await self.discover()
        # Sort by priority (lower = earlier)
        manifests.sort(key=lambda m: m.priority)
        for m in manifests:
            info = await self._registry.get(m.name)
            if info and not info.get("enabled", True):
                continue
            await self.load_from_directory(m.plugin_dir)

    async def load_builtin(self, builtin_dir: Path) -> int:
        """Load all builtin plugins from a directory, sorted by priority."""
        if not builtin_dir.exists():
            return 0

        manifests = []
        for p in builtin_dir.iterdir():
            if p.is_dir() and (p / ".claude-plugin" / "plugin.json").exists():
                try:
                    manifests.append(PluginManifest.from_directory(p))
                except Exception as e:
                    logger.warning("Failed to parse builtin plugin at %s: %s", p, e)

        # Sort by priority
        manifests.sort(key=lambda m: m.priority)
        loaded = 0
        for m in manifests:
            # Check registry override first, then enabled_by_default
            info = await self._registry.get(m.name)
            if info is not None:
                # User has explicitly set enabled state
                if not info.get("enabled", True):
                    logger.debug("Plugin '%s' disabled by user", m.name)
                    continue
            elif not m.enabled_by_default:
                logger.debug("Plugin '%s' disabled by default", m.name)
                continue
            result = await self.load_from_directory(m.plugin_dir)
            if result is not None:
                loaded += 1
        return loaded

    # ── Unloading ────────────────────────────────────────────────────────

    async def unload(self, plugin_name: str) -> None:
        components = self._loaded.pop(plugin_name, None)
        if not components:
            return

        # Teardown Python plugin
        if components.plugin_instance is not None:
            try:
                await components.plugin_instance.teardown()
            except Exception as e:
                logger.warning("Plugin '%s' teardown error: %s", plugin_name, e)

            # Unregister tools
            if self._tool_registry:
                for tool_func in components.plugin_instance.get_tools():
                    defn = getattr(tool_func, "_tool_definition", None)
                    if defn and hasattr(self._tool_registry, "unregister"):
                        self._tool_registry.unregister(defn.name)

        # Unregister coding agents
        try:
            from breadmind.coding.adapters import unregister_adapter
            for adapter in components.coding_agents:
                unregister_adapter(adapter.name)
        except ImportError:
            pass

        self._manifests.pop(plugin_name, None)
        logger.info("Unloaded plugin: %s", plugin_name)

        await get_event_bus().run_hook_chain(
            HookEvent.PLUGIN_UNLOADED,
            HookPayload(
                event=HookEvent.PLUGIN_UNLOADED,
                data={"plugin_name": plugin_name},
            ),
        )

    # ── Install / Uninstall ──────────────────────────────────────────────

    async def install(self, source: str) -> PluginManifest:
        source_path = Path(source)
        if source_path.is_dir():
            manifest = PluginManifest.from_directory(source_path)
            target = self._plugins_dir / manifest.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source_path, target)
            manifest = PluginManifest.from_directory(target)
            await self.load_from_directory(target)
            return manifest
        elif source.startswith(("https://", "git@")):
            import asyncio
            target_name = source.rstrip("/").split("/")[-1].replace(".git", "")
            target = self._plugins_dir / target_name
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", source, str(target),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"git clone failed for {source}")
            manifest = PluginManifest.from_directory(target)
            await self.load_from_directory(target)
            return manifest
        else:
            raise ValueError(f"Unknown install source: {source}")

    async def uninstall(self, plugin_name: str) -> None:
        await self.unload(plugin_name)
        target = self._plugins_dir / plugin_name
        if target.exists():
            shutil.rmtree(target)
        await self._registry.remove(plugin_name)
        logger.info("Uninstalled plugin: %s", plugin_name)

    # ── Utilities ────────────────────────────────────────────────────────

    def get_settings(self, plugin_name: str) -> dict:
        manifest = self._manifests.get(plugin_name)
        if manifest:
            return manifest.settings
        plugin_dir = self._plugins_dir / plugin_name
        if (plugin_dir / ".claude-plugin" / "plugin.json").exists():
            manifest = PluginManifest.from_directory(plugin_dir)
            return manifest.settings
        return {}

    def get_manifest(self, plugin_name: str) -> PluginManifest | None:
        return self._manifests.get(plugin_name)

    def get_all_tool_count(self) -> int:
        count = 0
        for comp in self._loaded.values():
            if comp.plugin_instance:
                count += len(comp.plugin_instance.get_tools())
        return count
