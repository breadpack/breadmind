"""Cross-ecosystem skill importer for BreadMind.

Auto-imports skills from Claude, Codex, and Cursor plugin formats
into BreadMind's native format.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class SourceFormat(str, Enum):
    CLAUDE = "claude"     # .claude/commands/, .claude/skills/
    CODEX = "codex"       # codex-config.json, agents/
    CURSOR = "cursor"     # .cursor/rules/, .cursorrules
    NATIVE = "native"     # BreadMind native


@dataclass
class ImportedSkill:
    name: str
    description: str
    content: str
    source_format: SourceFormat
    source_path: Path | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class ImportReport:
    total_found: int = 0
    imported: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    skills: list[ImportedSkill] = field(default_factory=list)


class SkillImporter:
    """Import skills from foreign plugin ecosystems.

    Detects and converts skills from:
    - Claude Code: .claude/commands/*.md, .claude/skills/*.md
    - Codex: codex-config.json with agents/
    - Cursor: .cursor/rules/*.md, .cursorrules
    """

    def __init__(self, project_dir: Path | None = None):
        self._project_dir = project_dir or Path.cwd()

    def detect_formats(self) -> list[SourceFormat]:
        """Detect which foreign formats are present in the project."""
        found: list[SourceFormat] = []
        claude_dir = self._project_dir / ".claude"
        if claude_dir.is_dir():
            commands = claude_dir / "commands"
            skills = claude_dir / "skills"
            if (commands.is_dir() and any(commands.glob("*.md"))) or (
                skills.is_dir() and any(skills.glob("*.md"))
            ):
                found.append(SourceFormat.CLAUDE)

        codex_cfg = self._project_dir / "codex-config.json"
        if codex_cfg.is_file():
            found.append(SourceFormat.CODEX)

        cursor_dir = self._project_dir / ".cursor"
        cursorrules = self._project_dir / ".cursorrules"
        if (cursor_dir.is_dir() and (cursor_dir / "rules").is_dir()) or cursorrules.is_file():
            found.append(SourceFormat.CURSOR)

        return found

    def import_all(self) -> ImportReport:
        """Import skills from all detected formats."""
        report = ImportReport()
        formats = self.detect_formats()

        importers = {
            SourceFormat.CLAUDE: self.import_claude,
            SourceFormat.CODEX: self.import_codex,
            SourceFormat.CURSOR: self.import_cursor,
        }

        for fmt in formats:
            importer = importers.get(fmt)
            if not importer:
                continue
            try:
                skills = importer()
                report.total_found += len(skills)
                for skill in skills:
                    report.skills.append(skill)
                    report.imported += 1
            except Exception as exc:
                report.errors.append(f"{fmt.value}: {exc}")

        return report

    def import_claude(self) -> list[ImportedSkill]:
        """Import from .claude/ directory."""
        skills: list[ImportedSkill] = []
        claude_dir = self._project_dir / ".claude"
        if not claude_dir.is_dir():
            return skills

        for subdir in ("commands", "skills"):
            target = claude_dir / subdir
            if not target.is_dir():
                continue
            for md_file in sorted(target.glob("*.md")):
                content = md_file.read_text(encoding="utf-8")
                name = md_file.stem
                description = self._extract_first_line(content)
                skills.append(
                    ImportedSkill(
                        name=name,
                        description=description,
                        content=content,
                        source_format=SourceFormat.CLAUDE,
                        source_path=md_file,
                        tags=["claude", subdir],
                    )
                )
        return skills

    def import_codex(self) -> list[ImportedSkill]:
        """Import from codex-config.json."""
        skills: list[ImportedSkill] = []
        config_path = self._project_dir / "codex-config.json"
        if not config_path.is_file():
            return skills

        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read codex-config.json: %s", exc)
            return skills

        # Import agents defined in config
        agents = data.get("agents", [])
        if isinstance(agents, list):
            for agent in agents:
                if isinstance(agent, dict):
                    name = agent.get("name", "unnamed")
                    desc = agent.get("description", "")
                    prompt = agent.get("prompt", "")
                    skills.append(
                        ImportedSkill(
                            name=name,
                            description=desc,
                            content=prompt,
                            source_format=SourceFormat.CODEX,
                            source_path=config_path,
                            tags=["codex", "agent"],
                        )
                    )

        # Import from agents/ directory
        agents_dir = self._project_dir / "agents"
        if agents_dir.is_dir():
            for md_file in sorted(agents_dir.glob("*.md")):
                content = md_file.read_text(encoding="utf-8")
                name = md_file.stem
                description = self._extract_first_line(content)
                skills.append(
                    ImportedSkill(
                        name=name,
                        description=description,
                        content=content,
                        source_format=SourceFormat.CODEX,
                        source_path=md_file,
                        tags=["codex", "agent"],
                    )
                )
        return skills

    def import_cursor(self) -> list[ImportedSkill]:
        """Import from .cursor/ or .cursorrules."""
        skills: list[ImportedSkill] = []

        # .cursor/rules/*.md
        rules_dir = self._project_dir / ".cursor" / "rules"
        if rules_dir.is_dir():
            for md_file in sorted(rules_dir.glob("*.md")):
                content = md_file.read_text(encoding="utf-8")
                name = md_file.stem
                description = self._extract_first_line(content)
                skills.append(
                    ImportedSkill(
                        name=name,
                        description=description,
                        content=content,
                        source_format=SourceFormat.CURSOR,
                        source_path=md_file,
                        tags=["cursor", "rule"],
                    )
                )

        # .cursorrules (single file with multiple rules)
        cursorrules = self._project_dir / ".cursorrules"
        if cursorrules.is_file():
            content = cursorrules.read_text(encoding="utf-8")
            skills.append(
                ImportedSkill(
                    name="cursorrules",
                    description=self._extract_first_line(content),
                    content=content,
                    source_format=SourceFormat.CURSOR,
                    source_path=cursorrules,
                    tags=["cursor", "rules"],
                )
            )

        return skills

    def convert_to_native(self, skill: ImportedSkill) -> dict:
        """Convert an imported skill to BreadMind's native skill format."""
        frontmatter = {
            "name": skill.name,
            "description": skill.description,
            "source_format": skill.source_format.value,
            "tags": skill.tags,
        }
        if skill.source_path:
            frontmatter["source_path"] = str(skill.source_path)

        return {
            "name": skill.name,
            "description": skill.description,
            "content": skill.content,
            "frontmatter": frontmatter,
        }

    def save_imported(
        self, skills: list[ImportedSkill], output_dir: Path | None = None
    ) -> list[Path]:
        """Save imported skills as .md files in BreadMind format."""
        out = output_dir or (self._project_dir / "skills" / "imported")
        out.mkdir(parents=True, exist_ok=True)

        saved: list[Path] = []
        for skill in skills:
            native = self.convert_to_native(skill)
            fm = native["frontmatter"]

            # Build markdown with YAML-like frontmatter
            lines = ["---"]
            lines.append(f"name: {fm['name']}")
            lines.append(f"description: {fm['description']}")
            lines.append(f"source_format: {fm['source_format']}")
            if fm.get("tags"):
                lines.append(f"tags: {', '.join(fm['tags'])}")
            if fm.get("source_path"):
                lines.append(f"source_path: {fm['source_path']}")
            lines.append("---")
            lines.append("")
            lines.append(native["content"])

            # Sanitize filename
            safe_name = re.sub(r"[^\w\-]", "_", skill.name)
            filepath = out / f"{safe_name}.md"
            filepath.write_text("\n".join(lines), encoding="utf-8")
            saved.append(filepath)
            logger.info("Saved imported skill: %s", filepath)

        return saved

    @staticmethod
    def _extract_first_line(content: str) -> str:
        """Extract the first non-empty, non-heading line as description."""
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            # Remove markdown heading prefix
            if stripped.startswith("#"):
                stripped = stripped.lstrip("#").strip()
            if stripped:
                return stripped[:200]
        return ""
