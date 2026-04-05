"""Conflict detector — detect naming conflicts between plugins, tools, skills, and MCP servers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("breadmind.plugins.conflict_detector")


class ConflictType(str, Enum):
    TOOL_NAME = "tool_name"
    SKILL_NAME = "skill_name"
    TRIGGER_KEYWORD = "trigger_keyword"
    MCP_TOOL = "mcp_tool"
    RESOURCE = "resource"


@dataclass
class Conflict:
    type: ConflictType
    name: str
    sources: list[str]
    severity: str = "warning"  # "error" or "warning"
    resolution: str = ""

    def __post_init__(self) -> None:
        if self.severity not in ("error", "warning"):
            raise ValueError(f"Invalid severity: {self.severity!r}")


@dataclass
class ConflictReport:
    conflicts: list[Conflict] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(c.severity == "error" for c in self.conflicts)

    @property
    def error_count(self) -> int:
        return sum(1 for c in self.conflicts if c.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for c in self.conflicts if c.severity == "warning")


class ConflictDetector:
    """Detects naming and resource conflicts between components.

    Checks:
    - Tool name collisions (builtin vs plugin vs MCP)
    - Skill name collisions
    - Trigger keyword overlaps between skills
    - MCP tool names shadowing builtins
    """

    def __init__(self) -> None:
        self._tool_registry: dict[str, list[str]] = {}  # name -> [sources]
        self._skill_registry: dict[str, list[str]] = {}  # name -> [sources]
        self._keyword_registry: dict[str, list[str]] = {}  # keyword -> [skill names]

    def register_tools(self, source: str, tool_names: list[str]) -> None:
        """Register tools from a source (e.g., 'builtin', 'plugin:github', 'mcp:postgres')."""
        for name in tool_names:
            self._tool_registry.setdefault(name, [])
            if source not in self._tool_registry[name]:
                self._tool_registry[name].append(source)

    def register_skills(self, source: str, skill_names: list[str]) -> None:
        """Register skills from a source."""
        for name in skill_names:
            self._skill_registry.setdefault(name, [])
            if source not in self._skill_registry[name]:
                self._skill_registry[name].append(source)

    def register_keywords(self, skill_name: str, keywords: list[str]) -> None:
        """Register trigger keywords for a skill."""
        for kw in keywords:
            normalized = kw.lower().strip()
            self._keyword_registry.setdefault(normalized, [])
            if skill_name not in self._keyword_registry[normalized]:
                self._keyword_registry[normalized].append(skill_name)

    def detect_all(self) -> ConflictReport:
        """Run all conflict detection checks."""
        conflicts: list[Conflict] = []
        conflicts.extend(self.detect_tool_conflicts())
        conflicts.extend(self.detect_skill_conflicts())
        conflicts.extend(self.detect_keyword_conflicts())
        return ConflictReport(conflicts=conflicts)

    def detect_tool_conflicts(self) -> list[Conflict]:
        """Detect tool name collisions across sources."""
        conflicts: list[Conflict] = []
        for name, sources in self._tool_registry.items():
            if len(sources) < 2:
                continue

            # MCP tool shadowing a builtin is an error
            has_builtin = any(s == "builtin" for s in sources)
            has_mcp = any(s.startswith("mcp:") for s in sources)

            if has_builtin and has_mcp:
                conflicts.append(Conflict(
                    type=ConflictType.MCP_TOOL,
                    name=name,
                    sources=list(sources),
                    severity="error",
                    resolution=f"Rename the MCP tool '{name}' or use a namespace prefix",
                ))
            else:
                conflicts.append(Conflict(
                    type=ConflictType.TOOL_NAME,
                    name=name,
                    sources=list(sources),
                    severity="warning",
                    resolution=f"Consider renaming tool '{name}' in one of the sources",
                ))
        return conflicts

    def detect_skill_conflicts(self) -> list[Conflict]:
        """Detect skill name collisions across sources."""
        conflicts: list[Conflict] = []
        for name, sources in self._skill_registry.items():
            if len(sources) < 2:
                continue
            conflicts.append(Conflict(
                type=ConflictType.SKILL_NAME,
                name=name,
                sources=list(sources),
                severity="warning",
                resolution=f"Rename skill '{name}' in one of the sources",
            ))
        return conflicts

    def detect_keyword_conflicts(self) -> list[Conflict]:
        """Detect trigger keyword overlaps between skills."""
        conflicts: list[Conflict] = []
        for keyword, skills in self._keyword_registry.items():
            if len(skills) < 2:
                continue
            conflicts.append(Conflict(
                type=ConflictType.TRIGGER_KEYWORD,
                name=keyword,
                sources=skills,
                severity="warning",
                resolution=(
                    f"Keyword '{keyword}' is claimed by multiple skills: "
                    f"{', '.join(skills)}"
                ),
            ))
        return conflicts

    def check_before_install(
        self,
        name: str,
        source: str,
        tool_names: list[str] | None = None,
        skill_names: list[str] | None = None,
    ) -> ConflictReport:
        """Pre-installation conflict check (doesn't modify registry)."""
        conflicts: list[Conflict] = []

        for tool in (tool_names or []):
            existing = self._tool_registry.get(tool, [])
            if existing:
                all_sources = existing + [source]
                has_builtin = any(s == "builtin" for s in all_sources)
                has_mcp = any(s.startswith("mcp:") for s in all_sources)

                if has_builtin and has_mcp:
                    severity = "error"
                    ctype = ConflictType.MCP_TOOL
                else:
                    severity = "warning"
                    ctype = ConflictType.TOOL_NAME

                conflicts.append(Conflict(
                    type=ctype,
                    name=tool,
                    sources=all_sources,
                    severity=severity,
                    resolution=f"Tool '{tool}' already registered by {', '.join(existing)}",
                ))

        for skill in (skill_names or []):
            existing = self._skill_registry.get(skill, [])
            if existing:
                conflicts.append(Conflict(
                    type=ConflictType.SKILL_NAME,
                    name=skill,
                    sources=existing + [source],
                    severity="warning",
                    resolution=f"Skill '{skill}' already registered by {', '.join(existing)}",
                ))

        return ConflictReport(conflicts=conflicts)

    def clear(self) -> None:
        """Clear all registrations."""
        self._tool_registry.clear()
        self._skill_registry.clear()
        self._keyword_registry.clear()

    def unregister_source(self, source: str) -> None:
        """Remove all registrations from a source."""
        for name in list(self._tool_registry):
            sources = self._tool_registry[name]
            if source in sources:
                sources.remove(source)
            if not sources:
                del self._tool_registry[name]

        for name in list(self._skill_registry):
            sources = self._skill_registry[name]
            if source in sources:
                sources.remove(source)
            if not sources:
                del self._skill_registry[name]
