"""Load modular instruction files from rules directories."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class LoadedRule:
    name: str
    content: str
    source_path: Path


class RulesLoader:
    """Load modular instruction files from .breadmind/rules/*.md"""

    def __init__(
        self,
        project_dir: Path | None = None,
        user_dir: Path | None = None,
    ) -> None:
        self._project_dir = project_dir  # .breadmind/rules/
        self._user_dir = user_dir  # ~/.breadmind/rules/

    def discover(self) -> list[LoadedRule]:
        """Find all .md files in rules directories, sorted by name.

        User rules are loaded first, then project rules. Within each
        directory files are sorted alphabetically by stem.
        """
        rules: list[LoadedRule] = []
        for rules_dir in (self._user_dir, self._project_dir):
            if rules_dir is None or not rules_dir.is_dir():
                continue
            md_files = sorted(rules_dir.glob("*.md"), key=lambda p: p.stem)
            for path in md_files:
                try:
                    content = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                rules.append(
                    LoadedRule(
                        name=path.stem,
                        content=content,
                        source_path=path,
                    )
                )
        return rules

    def load_all(self) -> str:
        """Load and concatenate all rules, separated by headers."""
        rules = self.discover()
        if not rules:
            return ""
        parts: list[str] = []
        for rule in rules:
            parts.append(f"## {rule.name}\n\n{rule.content.strip()}")
        return "\n\n".join(parts)

    def load_by_name(self, name: str) -> LoadedRule | None:
        """Load a specific rule file by name (without .md extension)."""
        for rules_dir in (self._user_dir, self._project_dir):
            if rules_dir is None or not rules_dir.is_dir():
                continue
            path = rules_dir / f"{name}.md"
            if path.is_file():
                try:
                    content = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                return LoadedRule(
                    name=name,
                    content=content,
                    source_path=path,
                )
        return None
