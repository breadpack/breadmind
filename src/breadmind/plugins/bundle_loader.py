"""Cross-format plugin bundle loader: detects and loads Codex/Claude/Cursor plugins."""
from __future__ import annotations
import json, logging, os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

class BundleFormat(str):
    NATIVE = "native"
    CODEX = "codex"
    CLAUDE = "claude"
    CURSOR = "cursor"

@dataclass
class DetectedBundle:
    format: str
    path: str
    name: str = ""
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)

class BundleLoader:
    """Detects and loads plugin bundles from multiple formats."""

    def detect_format(self, plugin_dir: str) -> str | None:
        """Detect plugin format from directory structure."""
        # Native format (highest priority)
        if os.path.exists(os.path.join(plugin_dir, "plugin.json")):
            return BundleFormat.NATIVE
        # Codex format
        if os.path.exists(os.path.join(plugin_dir, ".codex-plugin", "plugin.json")):
            return BundleFormat.CODEX
        # Claude format
        if os.path.exists(os.path.join(plugin_dir, ".claude", "settings.json")):
            return BundleFormat.CLAUDE
        if os.path.exists(os.path.join(plugin_dir, "CLAUDE.md")):
            return BundleFormat.CLAUDE
        # Cursor format
        if os.path.exists(os.path.join(plugin_dir, ".cursor-plugin", "plugin.json")):
            return BundleFormat.CURSOR
        if os.path.exists(os.path.join(plugin_dir, ".cursor", "rules")):
            return BundleFormat.CURSOR
        return None

    def load_bundle(self, plugin_dir: str) -> DetectedBundle | None:
        """Load a plugin bundle, translating to native format."""
        fmt = self.detect_format(plugin_dir)
        if fmt is None:
            return None

        if fmt == BundleFormat.NATIVE:
            return self._load_native(plugin_dir)
        elif fmt == BundleFormat.CODEX:
            return self._load_codex(plugin_dir)
        elif fmt == BundleFormat.CLAUDE:
            return self._load_claude(plugin_dir)
        elif fmt == BundleFormat.CURSOR:
            return self._load_cursor(plugin_dir)
        return None

    def _load_native(self, path: str) -> DetectedBundle:
        manifest = os.path.join(path, "plugin.json")
        with open(manifest) as f:
            data = json.load(f)
        return DetectedBundle(
            format=BundleFormat.NATIVE, path=path, name=data.get("name", ""),
            skills=self._find_skills(path),
            tools=[t.get("name", "") for t in data.get("x-breadmind", {}).get("tools", [])],
        )

    def _load_codex(self, path: str) -> DetectedBundle:
        manifest = os.path.join(path, ".codex-plugin", "plugin.json")
        data = {}
        if os.path.exists(manifest):
            with open(manifest) as f:
                data = json.load(f)
        return DetectedBundle(
            format=BundleFormat.CODEX, path=path, name=data.get("name", os.path.basename(path)),
            skills=self._find_skills(path),
        )

    def _load_claude(self, path: str) -> DetectedBundle:
        name = os.path.basename(path)
        skills = []
        # Claude commands/ directory maps to skills
        commands_dir = os.path.join(path, "commands")
        if os.path.isdir(commands_dir):
            for f in os.listdir(commands_dir):
                if f.endswith(".md"):
                    skills.append(f[:-3])

        mcp = []
        settings = os.path.join(path, ".claude", "settings.json")
        if os.path.exists(settings):
            try:
                with open(settings) as f:
                    data = json.load(f)
                mcp = list(data.get("mcpServers", {}).keys())
            except (json.JSONDecodeError, IOError):
                pass

        return DetectedBundle(
            format=BundleFormat.CLAUDE, path=path, name=name,
            skills=skills, mcp_servers=mcp,
        )

    def _load_cursor(self, path: str) -> DetectedBundle:
        name = os.path.basename(path)
        skills = []
        # Cursor commands/ maps to skills
        for cmd_dir in [os.path.join(path, ".cursor", "commands"),
                        os.path.join(path, ".cursor-plugin", "commands")]:
            if os.path.isdir(cmd_dir):
                for f in os.listdir(cmd_dir):
                    if f.endswith(".md"):
                        skills.append(f[:-3])

        return DetectedBundle(
            format=BundleFormat.CURSOR, path=path, name=name, skills=skills,
        )

    @staticmethod
    def _find_skills(path: str) -> list[str]:
        skills = []
        for skills_dir in ["skills", "commands"]:
            d = os.path.join(path, skills_dir)
            if os.path.isdir(d):
                for f in os.listdir(d):
                    if f.endswith(".md"):
                        skills.append(f[:-3])
        return skills
