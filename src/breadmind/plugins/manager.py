from __future__ import annotations

import logging
import shutil
from pathlib import Path

from breadmind.plugins.manifest import PluginManifest
from breadmind.plugins.loader import PluginLoader, LoadedComponents
from breadmind.plugins.registry import PluginRegistry

logger = logging.getLogger("breadmind.plugins")


class PluginManager:
    def __init__(
        self,
        plugins_dir: Path,
        tool_registry=None,
        prompt_builder=None,
        event_bus=None,
        db=None,
    ):
        self._plugins_dir = plugins_dir
        self._plugins_dir.mkdir(parents=True, exist_ok=True)
        self._registry = PluginRegistry(plugins_dir / "registry.json")
        self._loader = PluginLoader()
        self._tool_registry = tool_registry
        self._prompt_builder = prompt_builder
        self._event_bus = event_bus
        self._db = db
        self._loaded: dict[str, LoadedComponents] = {}

    @property
    def loaded_plugins(self) -> dict[str, LoadedComponents]:
        return dict(self._loaded)

    async def discover(self) -> list[PluginManifest]:
        manifests = []
        if not self._plugins_dir.exists():
            return manifests
        for p in self._plugins_dir.iterdir():
            if (p / ".claude-plugin" / "plugin.json").exists():
                try:
                    manifests.append(PluginManifest.from_directory(p))
                except Exception as e:
                    logger.warning(f"Failed to parse plugin at {p}: {e}")
        return manifests

    async def load(self, plugin_name: str) -> LoadedComponents | None:
        plugin_dir = self._plugins_dir / plugin_name
        if not (plugin_dir / ".claude-plugin" / "plugin.json").exists():
            logger.warning(f"Plugin not found: {plugin_name}")
            return None
        return await self.load_from_directory(plugin_dir)

    async def load_from_directory(self, plugin_dir: Path) -> LoadedComponents | None:
        try:
            manifest = PluginManifest.from_directory(plugin_dir)
        except Exception as e:
            logger.warning(f"Failed to load plugin at {plugin_dir}: {e}")
            return None

        components = self._loader.load(manifest)
        self._loaded[manifest.name] = components

        # Register coding agents
        from breadmind.coding.adapters import register_adapter
        for adapter in components.coding_agents:
            register_adapter(adapter.name, adapter)
            logger.info(f"Registered coding agent: {adapter.name} from plugin {manifest.name}")

        # Register in registry
        await self._registry.add(manifest.name, {
            "version": manifest.version,
            "enabled": True,
            "path": str(plugin_dir),
            "description": manifest.description,
        })

        logger.info(f"Loaded plugin: {manifest.name} v{manifest.version}")
        return components

    async def unload(self, plugin_name: str):
        components = self._loaded.pop(plugin_name, None)
        if components:
            from breadmind.coding.adapters import unregister_adapter
            for adapter in components.coding_agents:
                unregister_adapter(adapter.name)
            logger.info(f"Unloaded plugin: {plugin_name}")

    async def install(self, source: str) -> PluginManifest:
        source_path = Path(source)
        if source_path.is_dir():
            # Local install — copy
            manifest = PluginManifest.from_directory(source_path)
            target = self._plugins_dir / manifest.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source_path, target)
            manifest = PluginManifest.from_directory(target)
            await self.load_from_directory(target)
            return manifest
        elif source.startswith(("https://", "git@")):
            # Git install
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

    async def uninstall(self, plugin_name: str):
        await self.unload(plugin_name)
        target = self._plugins_dir / plugin_name
        if target.exists():
            shutil.rmtree(target)
        await self._registry.remove(plugin_name)
        logger.info(f"Uninstalled plugin: {plugin_name}")

    async def load_all(self):
        manifests = await self.discover()
        for m in manifests:
            info = await self._registry.get(m.name)
            if info and not info.get("enabled", True):
                continue
            await self.load_from_directory(m.plugin_dir)

    def get_settings(self, plugin_name: str) -> dict:
        plugin_dir = self._plugins_dir / plugin_name
        if (plugin_dir / ".claude-plugin" / "plugin.json").exists():
            manifest = PluginManifest.from_directory(plugin_dir)
            return manifest.settings
        return {}
