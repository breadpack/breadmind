from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from breadmind.plugins.manifest import PluginManifest
from breadmind.plugins.declarative_adapter import DeclarativeAdapter


@dataclass
class LoadedComponents:
    commands: list[dict] = field(default_factory=list)
    skills: list[dict] = field(default_factory=list)
    agents: list[dict] = field(default_factory=list)
    hooks: list[dict] = field(default_factory=list)
    coding_agents: list[DeclarativeAdapter] = field(default_factory=list)
    roles: list[dict] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)


class PluginLoader:
    def load(self, manifest: PluginManifest) -> LoadedComponents:
        components = LoadedComponents()
        plugin_dir = manifest.plugin_dir
        if not plugin_dir:
            return components

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

        # Tools (x-breadmind)
        components.tools = list(manifest.tools)

        return components

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
