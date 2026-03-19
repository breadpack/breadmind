from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PluginManifest:
    name: str
    version: str
    description: str = ""
    author: str = ""
    commands_dir: str = "commands/"
    skills_dir: str = "skills/"
    agents_dir: str = "agents/"
    hooks_file: str = "hooks/"
    coding_agents: list[dict] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)
    mcp_servers: str = ""
    requires: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    plugin_dir: Path | None = None
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict, plugin_dir: Path | None = None) -> PluginManifest:
        if "name" not in data:
            raise ValueError("plugin.json must have 'name' field")
        if "version" not in data:
            raise ValueError("plugin.json must have 'version' field")
        x = data.get("x-breadmind", {})
        return cls(
            name=data["name"],
            version=data["version"],
            description=data.get("description", ""),
            author=data.get("author", ""),
            commands_dir=data.get("commands", "commands/"),
            skills_dir=data.get("skills", "skills/"),
            agents_dir=data.get("agents", "agents/"),
            hooks_file=data.get("hooks", "hooks/"),
            coding_agents=x.get("coding_agents", []),
            roles=x.get("roles", []),
            tools=x.get("tools", []),
            mcp_servers=x.get("mcp_servers", ""),
            requires=x.get("requires", {}),
            settings=x.get("settings", {}),
            plugin_dir=plugin_dir,
        )

    @classmethod
    def from_directory(cls, plugin_dir: Path) -> PluginManifest:
        manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"No plugin.json at {manifest_path}")
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return cls.from_dict(data, plugin_dir=plugin_dir)
