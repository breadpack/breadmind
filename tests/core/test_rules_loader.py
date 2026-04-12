"""Tests for the rules directory loader."""

from __future__ import annotations

from pathlib import Path

from breadmind.core.rules_loader import RulesLoader


class TestDiscover:
    def test_discover_project_rules(self, tmp_path: Path):
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        (rules_dir / "safety.md").write_text("Do not delete production data.")
        (rules_dir / "coding.md").write_text("Use async/await.")

        loader = RulesLoader(project_dir=rules_dir)
        rules = loader.discover()
        assert len(rules) == 2
        assert rules[0].name == "coding"
        assert rules[1].name == "safety"

    def test_discover_empty_dir(self, tmp_path: Path):
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        loader = RulesLoader(project_dir=rules_dir)
        assert loader.discover() == []

    def test_discover_nonexistent_dir(self):
        loader = RulesLoader(project_dir=Path("/nonexistent/rules"))
        assert loader.discover() == []

    def test_discover_both_user_and_project(self, tmp_path: Path):
        user_dir = tmp_path / "user_rules"
        user_dir.mkdir()
        (user_dir / "global.md").write_text("Global rule")

        project_dir = tmp_path / "project_rules"
        project_dir.mkdir()
        (project_dir / "local.md").write_text("Local rule")

        loader = RulesLoader(project_dir=project_dir, user_dir=user_dir)
        rules = loader.discover()
        assert len(rules) == 2
        # User rules come first
        assert rules[0].name == "global"
        assert rules[1].name == "local"


class TestLoadAll:
    def test_load_all_concatenation(self, tmp_path: Path):
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        (rules_dir / "alpha.md").write_text("Rule alpha content")
        (rules_dir / "beta.md").write_text("Rule beta content")

        loader = RulesLoader(project_dir=rules_dir)
        result = loader.load_all()
        assert "## alpha" in result
        assert "Rule alpha content" in result
        assert "## beta" in result
        assert "Rule beta content" in result

    def test_load_all_empty(self):
        loader = RulesLoader()
        assert loader.load_all() == ""


class TestLoadByName:
    def test_load_existing_rule(self, tmp_path: Path):
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        (rules_dir / "safety.md").write_text("Safety first.")

        loader = RulesLoader(project_dir=rules_dir)
        rule = loader.load_by_name("safety")
        assert rule is not None
        assert rule.name == "safety"
        assert rule.content == "Safety first."

    def test_load_missing_rule(self, tmp_path: Path):
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        loader = RulesLoader(project_dir=rules_dir)
        assert loader.load_by_name("nonexistent") is None

    def test_load_by_name_prefers_user_dir(self, tmp_path: Path):
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        (user_dir / "shared.md").write_text("User version")

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "shared.md").write_text("Project version")

        loader = RulesLoader(project_dir=project_dir, user_dir=user_dir)
        rule = loader.load_by_name("shared")
        assert rule is not None
        assert rule.content == "User version"
