"""Plugin loader — supports both Python-based and declarative plugins."""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from breadmind.plugins.manifest import PluginManifest
from breadmind.plugins.protocol import BaseToolPlugin, ToolPlugin

logger = logging.getLogger("breadmind.plugins")


@dataclass
class LoadedComponents:
    """Components extracted from a loaded plugin."""
    plugin_instance: ToolPlugin | None = None
    commands: list[dict] = field(default_factory=list)
    skills: list[dict] = field(default_factory=list)
    agents: list[dict] = field(default_factory=list)
    hooks: list[dict] = field(default_factory=list)
    coding_agents: list = field(default_factory=list)
    roles: list[dict] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)


class PluginLoader:
    """Loads plugins from directories.

    Supports two modes:
    1. **Python-based**: plugin directory contains a Python module with a
       ``ToolPlugin`` class or a ``create_plugin(container)`` factory.
    2. **Declarative**: plugin directory contains markdown commands/skills/agents
       (legacy format).
    """

    def load(self, manifest: PluginManifest) -> LoadedComponents:
        """Load plugin components from the manifest's directory."""
        components = LoadedComponents()
        plugin_dir = manifest.plugin_dir
        if not plugin_dir:
            return components

        # Try Python-based loading first
        py_module_path = plugin_dir / f"{manifest.python_module}.py"
        if py_module_path.exists():
            components.plugin_instance = self._load_python_plugin(
                manifest, py_module_path,
            )

        # Load declarative components (commands, skills, agents, hooks)
        self._load_declarative(manifest, components)

        return components

    def _load_python_plugin(
        self, manifest: PluginManifest, module_path: Path,
    ) -> ToolPlugin | None:
        """Import a Python module and extract a ToolPlugin instance."""
        module_name = f"breadmind.plugins.loaded.{manifest.name.replace('-', '_')}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec is None or spec.loader is None:
                logger.warning("Cannot load module spec: %s", module_path)
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # Look for a ToolPlugin subclass
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and attr is not BaseToolPlugin
                    and issubclass(attr, BaseToolPlugin)
                ):
                    instance = attr()
                    logger.debug("Found plugin class: %s in %s", attr_name, module_path)
                    return instance

            # Look for create_plugin() factory
            factory = getattr(module, "create_plugin", None)
            if callable(factory):
                instance = factory()
                logger.debug("Created plugin via factory in %s", module_path)
                return instance

            logger.warning("No ToolPlugin class or create_plugin() in %s", module_path)
            return None

        except Exception as e:
            logger.error("Failed to load Python plugin %s: %s", manifest.name, e)
            sys.modules.pop(module_name, None)
            return None

    def _load_declarative(
        self, manifest: PluginManifest, components: LoadedComponents,
    ) -> None:
        """Load declarative components (commands, skills, agents, hooks, coding agents)."""
        plugin_dir = manifest.plugin_dir
        if not plugin_dir:
            return

        # Commands
        cmd_dir = plugin_dir / manifest.commands_dir
        if cmd_dir.is_dir():
            for f in cmd_dir.glob("*.md"):
                components.commands.append(self._parse_command(f))

        # Skills
        skills_dir = plugin_dir / manifest.skills_dir
        if skills_dir.is_dir():
            for f in skills_dir.glob("*.md"):
                components.skills.append({
                    "name": f.stem,
                    "content": f.read_text(encoding="utf-8"),
                    "path": str(f),
                })

        # Agents
        agents_dir = plugin_dir / manifest.agents_dir
        if agents_dir.is_dir():
            for f in agents_dir.glob("*.md"):
                components.agents.append({
                    "name": f.stem,
                    "content": f.read_text(encoding="utf-8"),
                    "path": str(f),
                })

        # Hooks
        hooks_dir = plugin_dir / manifest.hooks_file
        hooks_json = (
            hooks_dir / "hooks.json" if hooks_dir.is_dir()
            else plugin_dir / "hooks.json"
        )
        if hooks_json.exists():
            components.hooks = json.loads(hooks_json.read_text(encoding="utf-8"))

        # Coding agents (x-breadmind)
        from breadmind.plugins.declarative_adapter import DeclarativeAdapter
        for config in manifest.coding_agents:
            components.coding_agents.append(DeclarativeAdapter(config))

        # Roles (x-breadmind)
        for role_path in manifest.roles:
            full_path = plugin_dir / role_path
            if full_path.exists():
                components.roles.append({
                    "name": full_path.stem,
                    "content": full_path.read_text(encoding="utf-8"),
                    "path": str(full_path),
                })

        # Tools (x-breadmind declarative)
        components.tools = list(manifest.tools)

    def _parse_command(self, path: Path) -> dict:
        content = path.read_text(encoding="utf-8")
        frontmatter = {}
        body = content
        match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)', content, re.DOTALL)
        if match:
            try:
                import yaml
                frontmatter = yaml.safe_load(match.group(1)) or {}
            except Exception:
                pass
            body = match.group(2)
        return {
            "name": path.stem,
            "description": frontmatter.get("description", ""),
            "content": body.strip(),
            "frontmatter": frontmatter,
            "path": str(path),
        }
