from __future__ import annotations

from pathlib import Path


class ProjectConfigManager:
    _CONFIG_MAP: dict[str, str] = {
        "claude": "CLAUDE.md",
        "codex": "AGENTS.md",
        "gemini": "GEMINI.md",
    }

    def get_config_path(self, project: str, agent: str) -> Path:
        filename = self._CONFIG_MAP.get(agent, f"{agent.upper()}.md")
        return Path(project) / filename

    def ensure_config(self, project: str, agent: str) -> Path | None:
        path = self.get_config_path(project, agent)
        return path if path.exists() else None
