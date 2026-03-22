"""Plugin manifest — supports both JSON-based and Python-based plugins."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SafetyDeclaration:
    """Safety policy declared by a plugin for its tools."""
    require_approval: list[str] = field(default_factory=list)
    blacklist: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> SafetyDeclaration:
        return cls(
            require_approval=data.get("require_approval", []),
            blacklist=data.get("blacklist", []),
        )


@dataclass
class PluginManifest:
    name: str
    version: str
    description: str = ""
    author: str = ""
    # Plugin loading
    priority: int = 100
    depends_on: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    optional_requires: list[str] = field(default_factory=list)
    python_module: str = "plugin"
    enabled_by_default: bool = True
    # Safety
    safety: SafetyDeclaration = field(default_factory=SafetyDeclaration)
    # Legacy fields (for external/declarative plugins)
    commands_dir: str = "commands/"
    skills_dir: str = "skills/"
    agents_dir: str = "agents/"
    hooks_file: str = "hooks/"
    coding_agents: list[dict] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)
    mcp_servers: str = ""
    settings: dict = field(default_factory=dict)
    # Internal
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
            priority=x.get("priority", 100),
            depends_on=x.get("depends_on", []),
            requires=x.get("requires", []),
            optional_requires=x.get("optional_requires", []),
            python_module=x.get("python_module", "plugin"),
            enabled_by_default=x.get("enabled_by_default", True),
            safety=SafetyDeclaration.from_dict(x.get("safety", {})),
            commands_dir=data.get("commands", "commands/"),
            skills_dir=data.get("skills", "skills/"),
            agents_dir=data.get("agents", "agents/"),
            hooks_file=data.get("hooks", "hooks/"),
            coding_agents=x.get("coding_agents", []),
            roles=x.get("roles", []),
            tools=x.get("tools", []),
            mcp_servers=x.get("mcp_servers", ""),
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
