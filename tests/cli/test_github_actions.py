"""Tests for GitHub Actions Integration."""

from __future__ import annotations

import pytest

from breadmind.cli.github_actions import ActionConfig, GitHubActionsGenerator


class TestGitHubActionsGenerator:
    def test_list_templates(self):
        gen = GitHubActionsGenerator()
        templates = gen.list_templates()
        assert "code-review" in templates
        assert "pr-description" in templates
        assert "test-generation" in templates
        assert "dependency-audit" in templates

    def test_generate_code_review(self):
        gen = GitHubActionsGenerator()
        yaml = gen.generate("code-review")
        assert "BreadMind Code Review" in yaml
        assert "pull_request" in yaml
        assert "actions/checkout@v4" in yaml

    def test_generate_with_custom_config(self):
        gen = GitHubActionsGenerator()
        config = ActionConfig(model="gpt-4", timeout_minutes=20)
        yaml = gen.generate("code-review", config)
        assert "gpt-4" in yaml
        assert "20" in yaml

    def test_generate_unknown_template_raises(self):
        gen = GitHubActionsGenerator()
        with pytest.raises(ValueError, match="Unknown template"):
            gen.generate("nonexistent")

    def test_generate_pr_description(self):
        gen = GitHubActionsGenerator()
        yaml = gen.generate("pr-description")
        assert "PR Description" in yaml
        assert "pr-describe" in yaml

    def test_generate_test_generation(self):
        gen = GitHubActionsGenerator()
        yaml = gen.generate("test-generation")
        assert "generate-tests" in yaml

    def test_generate_dependency_audit(self):
        gen = GitHubActionsGenerator()
        yaml = gen.generate("dependency-audit")
        assert "Dependency Audit" in yaml
        assert "audit-deps" in yaml

    def test_install_creates_file(self, tmp_path):
        gen = GitHubActionsGenerator(project_root=tmp_path)
        path = gen.install("code-review")
        assert path.exists()
        assert path.name == "breadmind-code-review.yml"
        content = path.read_text()
        assert "BreadMind Code Review" in content
