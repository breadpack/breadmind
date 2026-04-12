"""Usage-based tool and skill recommendation engine."""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass


@dataclass
class UsageRecord:
    tool_name: str
    timestamp: float
    success: bool = True
    context: str = ""  # What the user was working on


@dataclass
class Recommendation:
    name: str
    type: str  # "tool", "skill", "mcp_server", "search_provider"
    reason: str
    confidence: float  # 0.0-1.0
    install_command: str = ""


class AutoRecommender:
    """Recommends tools, skills, and MCP servers based on usage patterns.

    Analyzes:
    - Frequently used tools -> suggest related tools
    - Failed tool calls -> suggest alternatives
    - Project type detection -> suggest domain tools
    - Missing capabilities -> suggest MCP servers
    """

    # Maps tool usage to related recommendations.
    RELATED_MAP: dict[str, list[tuple[str, str, str]]] = {
        # tool_name -> [(recommended, type, reason)]
        "git_commit": [
            (
                "github",
                "mcp_server",
                "You use git frequently -- GitHub MCP server adds PR/issue management",
            ),
        ],
        "shell_exec": [
            (
                "filesystem",
                "mcp_server",
                "Heavy shell usage -- filesystem MCP provides structured file access",
            ),
        ],
        "web_search": [
            (
                "brave-search",
                "mcp_server",
                "Enhance search with Brave's focused results",
            ),
            (
                "tavily",
                "search_provider",
                "Tavily provides LLM-optimized search results",
            ),
        ],
        "file_read": [
            (
                "lsp_goto_definition",
                "tool",
                "You read files often -- LSP tools add code intelligence",
            ),
        ],
        "notebook_read": [
            (
                "data-analysis",
                "skill",
                "Jupyter usage detected -- data analysis skill can help",
            ),
        ],
    }

    # Project type -> recommended packages.
    PROJECT_RECOMMENDATIONS: dict[str, list[tuple[str, str, str]]] = {
        "python": [
            ("python-lsp", "mcp_server", "Python LSP for code intelligence"),
        ],
        "javascript": [
            ("typescript-lsp", "mcp_server", "TypeScript/JS LSP for code intelligence"),
        ],
        "docker": [
            ("docker", "skill", "Docker management skill"),
        ],
        "kubernetes": [
            ("kubernetes", "skill", "Kubernetes operations skill"),
        ],
    }

    # File patterns for project type detection.
    _PROJECT_PATTERNS: dict[str, list[str]] = {
        "python": ["*.py", "pyproject.toml", "setup.py", "requirements.txt"],
        "javascript": ["*.js", "*.ts", "package.json", "tsconfig.json"],
        "docker": ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"],
        "kubernetes": ["*.yaml", "*.yml", "kustomization.yaml", "Chart.yaml"],
    }

    def __init__(self, max_history: int = 1000) -> None:
        self._history: list[UsageRecord] = []
        self._max_history = max_history
        self._dismissed: set[str] = set()

    # -- Recording --

    def record_usage(
        self, tool_name: str, success: bool = True, context: str = ""
    ) -> None:
        """Record a tool usage event."""
        record = UsageRecord(
            tool_name=tool_name,
            timestamp=time.time(),
            success=success,
            context=context,
        )
        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

    # -- Recommendations --

    def get_recommendations(
        self, limit: int = 5, installed: set[str] | None = None
    ) -> list[Recommendation]:
        """Get recommendations based on usage history.
        Excludes already installed and dismissed items.
        """
        installed = installed or set()

        recs: list[Recommendation] = []
        recs.extend(self.get_usage_based_recommendations(installed))
        recs.extend(self.get_failure_based_recommendations(installed))

        # De-duplicate by name, keeping highest confidence.
        seen: dict[str, Recommendation] = {}
        for r in recs:
            if r.name in self._dismissed:
                continue
            if r.name not in seen or r.confidence > seen[r.name].confidence:
                seen[r.name] = r

        sorted_recs = sorted(seen.values(), key=lambda r: r.confidence, reverse=True)
        return sorted_recs[:limit]

    def get_usage_based_recommendations(
        self, installed: set[str]
    ) -> list[Recommendation]:
        """Recommend based on tool usage frequency."""
        counter = Counter(r.tool_name for r in self._history)
        total = len(self._history) or 1
        recs: list[Recommendation] = []

        for tool_name, count in counter.most_common():
            related = self.RELATED_MAP.get(tool_name, [])
            for rec_name, rec_type, reason in related:
                if rec_name in installed or rec_name in self._dismissed:
                    continue
                confidence = min(count / total * 2.0, 0.95)
                recs.append(
                    Recommendation(
                        name=rec_name,
                        type=rec_type,
                        reason=reason,
                        confidence=round(confidence, 2),
                    )
                )

        return recs

    def get_failure_based_recommendations(
        self, installed: set[str]
    ) -> list[Recommendation]:
        """Recommend based on failed tool calls (suggest alternatives)."""
        failures = Counter(
            r.tool_name for r in self._history if not r.success
        )
        total_failures = sum(failures.values()) or 1
        recs: list[Recommendation] = []

        for tool_name, fail_count in failures.most_common():
            related = self.RELATED_MAP.get(tool_name, [])
            for rec_name, rec_type, reason in related:
                if rec_name in installed or rec_name in self._dismissed:
                    continue
                confidence = min(fail_count / total_failures * 1.5, 0.9)
                recs.append(
                    Recommendation(
                        name=rec_name,
                        type=rec_type,
                        reason=f"Failures in '{tool_name}' detected -- {reason}",
                        confidence=round(confidence, 2),
                    )
                )

        return recs

    def detect_project_type(
        self, file_patterns: list[str] | None = None
    ) -> list[str]:
        """Detect project type from file patterns."""
        if not file_patterns:
            return []

        detected: list[str] = []
        for project_type, patterns in self._PROJECT_PATTERNS.items():
            for fp in file_patterns:
                # Simple suffix/name match.
                for pattern in patterns:
                    pat = pattern.lstrip("*")
                    if fp.endswith(pat) or fp == pattern:
                        if project_type not in detected:
                            detected.append(project_type)
                        break
        return detected

    def get_project_recommendations(
        self, project_types: list[str], installed: set[str]
    ) -> list[Recommendation]:
        """Recommend based on detected project types."""
        recs: list[Recommendation] = []
        for pt in project_types:
            items = self.PROJECT_RECOMMENDATIONS.get(pt, [])
            for rec_name, rec_type, reason in items:
                if rec_name in installed or rec_name in self._dismissed:
                    continue
                recs.append(
                    Recommendation(
                        name=rec_name,
                        type=rec_type,
                        reason=reason,
                        confidence=0.7,
                    )
                )
        return recs

    def dismiss(self, name: str) -> None:
        """Dismiss a recommendation (don't show again)."""
        self._dismissed.add(name)

    # -- Statistics --

    def get_usage_stats(self) -> dict:
        """Return tool usage statistics."""
        if not self._history:
            return {
                "total_calls": 0,
                "unique_tools": 0,
                "success_rate": 0.0,
                "top_tools": [],
            }

        total = len(self._history)
        successes = sum(1 for r in self._history if r.success)
        counter = Counter(r.tool_name for r in self._history)

        return {
            "total_calls": total,
            "unique_tools": len(counter),
            "success_rate": round(successes / total, 2),
            "top_tools": counter.most_common(10),
        }

    def get_top_tools(self, limit: int = 10) -> list[tuple[str, int]]:
        """Most used tools."""
        counter = Counter(r.tool_name for r in self._history)
        return counter.most_common(limit)

    def get_failure_rate(self) -> dict[str, float]:
        """Per-tool failure rates."""
        total_per_tool: Counter[str] = Counter()
        fail_per_tool: Counter[str] = Counter()

        for r in self._history:
            total_per_tool[r.tool_name] += 1
            if not r.success:
                fail_per_tool[r.tool_name] += 1

        return {
            tool: round(fail_per_tool[tool] / count, 2)
            for tool, count in total_per_tool.items()
        }
