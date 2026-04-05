"""Tests for cross-ecosystem skill importer."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from breadmind.plugins.skill_importer import (
    ImportedSkill,
    ImportReport,
    SkillImporter,
    SourceFormat,
)


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def importer(project_dir: Path) -> SkillImporter:
    return SkillImporter(project_dir=project_dir)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# --- detect_formats ---


def test_detect_no_formats(importer: SkillImporter):
    assert importer.detect_formats() == []


def test_detect_claude_format(project_dir: Path, importer: SkillImporter):
    _write(project_dir / ".claude" / "commands" / "deploy.md", "# Deploy\nDeploy to prod")
    found = importer.detect_formats()
    assert SourceFormat.CLAUDE in found


def test_detect_codex_format(project_dir: Path, importer: SkillImporter):
    _write(project_dir / "codex-config.json", json.dumps({"agents": []}))
    found = importer.detect_formats()
    assert SourceFormat.CODEX in found


def test_detect_cursor_format_rules_dir(project_dir: Path, importer: SkillImporter):
    _write(project_dir / ".cursor" / "rules" / "style.md", "# Style guide")
    found = importer.detect_formats()
    assert SourceFormat.CURSOR in found


def test_detect_cursor_format_cursorrules(project_dir: Path, importer: SkillImporter):
    _write(project_dir / ".cursorrules", "Be concise.")
    found = importer.detect_formats()
    assert SourceFormat.CURSOR in found


# --- import_claude ---


def test_import_claude_commands_and_skills(project_dir: Path, importer: SkillImporter):
    _write(project_dir / ".claude" / "commands" / "deploy.md", "# Deploy\nDeploy to production")
    _write(project_dir / ".claude" / "skills" / "debug.md", "# Debug\nDebug the app")
    skills = importer.import_claude()
    assert len(skills) == 2
    names = {s.name for s in skills}
    assert names == {"deploy", "debug"}
    for s in skills:
        assert s.source_format == SourceFormat.CLAUDE
        assert s.source_path is not None


def test_import_claude_empty_dir(project_dir: Path, importer: SkillImporter):
    # No .claude dir at all
    skills = importer.import_claude()
    assert skills == []


# --- import_codex ---


def test_import_codex_agents_from_config(project_dir: Path, importer: SkillImporter):
    config = {
        "agents": [
            {"name": "reviewer", "description": "Code reviewer", "prompt": "Review this code"},
            {"name": "writer", "description": "Doc writer", "prompt": "Write docs"},
        ]
    }
    _write(project_dir / "codex-config.json", json.dumps(config))
    skills = importer.import_codex()
    assert len(skills) == 2
    assert skills[0].name == "reviewer"
    assert skills[0].content == "Review this code"
    assert skills[0].source_format == SourceFormat.CODEX


def test_import_codex_agents_dir(project_dir: Path, importer: SkillImporter):
    _write(project_dir / "codex-config.json", json.dumps({}))
    _write(project_dir / "agents" / "helper.md", "# Helper\nI help with stuff")
    skills = importer.import_codex()
    assert len(skills) == 1
    assert skills[0].name == "helper"


# --- import_cursor ---


def test_import_cursor_rules(project_dir: Path, importer: SkillImporter):
    _write(project_dir / ".cursor" / "rules" / "typescript.md", "# TypeScript Rules\nUse strict mode")
    skills = importer.import_cursor()
    assert len(skills) == 1
    assert skills[0].name == "typescript"
    assert "cursor" in skills[0].tags


def test_import_cursorrules_file(project_dir: Path, importer: SkillImporter):
    _write(project_dir / ".cursorrules", "Always use type hints.")
    skills = importer.import_cursor()
    assert len(skills) == 1
    assert skills[0].name == "cursorrules"
    assert skills[0].description == "Always use type hints."


# --- import_all ---


def test_import_all_multiple_formats(project_dir: Path, importer: SkillImporter):
    _write(project_dir / ".claude" / "commands" / "build.md", "# Build\nBuild the project")
    _write(project_dir / "codex-config.json", json.dumps({"agents": [{"name": "a1", "description": "d", "prompt": "p"}]}))
    report = importer.import_all()
    assert isinstance(report, ImportReport)
    assert report.total_found >= 2
    assert report.imported >= 2
    assert len(report.skills) >= 2


# --- convert_to_native ---


def test_convert_to_native(importer: SkillImporter):
    skill = ImportedSkill(
        name="deploy",
        description="Deploy to prod",
        content="Run deploy script",
        source_format=SourceFormat.CLAUDE,
        source_path=Path("/some/path/deploy.md"),
        tags=["claude", "commands"],
    )
    native = importer.convert_to_native(skill)
    assert native["name"] == "deploy"
    assert native["description"] == "Deploy to prod"
    assert native["content"] == "Run deploy script"
    assert native["frontmatter"]["source_format"] == "claude"
    assert native["frontmatter"]["tags"] == ["claude", "commands"]


# --- save_imported ---


def test_save_imported(project_dir: Path, importer: SkillImporter):
    skills = [
        ImportedSkill(
            name="my-skill",
            description="A test skill",
            content="Do something useful",
            source_format=SourceFormat.CURSOR,
            tags=["cursor", "rule"],
        ),
    ]
    output_dir = project_dir / "output"
    paths = importer.save_imported(skills, output_dir=output_dir)
    assert len(paths) == 1
    assert paths[0].exists()
    content = paths[0].read_text(encoding="utf-8")
    assert "name: my-skill" in content
    assert "source_format: cursor" in content
    assert "Do something useful" in content


# --- edge cases ---


def test_extract_first_line_skips_empty_and_headings():
    importer = SkillImporter()
    assert importer._extract_first_line("") == ""
    assert importer._extract_first_line("\n\n") == ""
    assert importer._extract_first_line("# Heading\nBody text") == "Heading"
    assert importer._extract_first_line("\n\nFirst real line") == "First real line"
