"""GitHub Actions Integration — generate and manage CI/CD workflows.

Provides templates for common BreadMind automation use cases:
automated code review, PR description generation, test generation,
and dependency auditing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent

from breadmind.constants import DEFAULT_CLAUDE_MODEL


@dataclass
class ActionConfig:
    trigger: str = "pull_request"
    model: str = DEFAULT_CLAUDE_MODEL
    allowed_tools: list[str] = field(default_factory=list)
    prompt: str = ""
    timeout_minutes: int = 10


class GitHubActionsGenerator:
    """Generate GitHub Actions workflows for BreadMind automation.

    Use cases:
    - Automated code review on PRs
    - PR description generation
    - Test generation for new files
    - Dependency audit on schedule
    """

    TEMPLATES: dict[str, str] = {
        "code-review": "code-review",
        "pr-description": "pr-description",
        "test-generation": "test-generation",
        "dependency-audit": "dependency-audit",
    }

    def __init__(self, project_root: Path | None = None) -> None:
        self._root = project_root or Path.cwd()

    def generate(self, template: str, config: ActionConfig | None = None) -> str:
        """Generate a workflow YAML string from a template."""
        if template not in self.TEMPLATES:
            raise ValueError(
                f"Unknown template {template!r}. "
                f"Available: {', '.join(self.TEMPLATES)}"
            )
        config = config or ActionConfig()
        renderer = {
            "code-review": self._render_code_review,
            "pr-description": self._render_pr_description,
            "test-generation": self._render_test_generation,
            "dependency-audit": self._render_dependency_audit,
        }[template]
        return renderer(config)

    def install(self, template: str, config: ActionConfig | None = None) -> Path:
        """Generate and write workflow to .github/workflows/.  Returns path."""
        content = self.generate(template, config)
        workflows_dir = self._root / ".github" / "workflows"
        workflows_dir.mkdir(parents=True, exist_ok=True)
        path = workflows_dir / f"breadmind-{template}.yml"
        path.write_text(content, encoding="utf-8")
        return path

    def list_templates(self) -> list[str]:
        return list(self.TEMPLATES.keys())

    # ---- renderers --------------------------------------------------------

    def _render_code_review(self, config: ActionConfig) -> str:
        return dedent(f"""\
            name: BreadMind Code Review
            on:
              {config.trigger}:
                types: [opened, synchronize]
            jobs:
              review:
                runs-on: ubuntu-latest
                timeout-minutes: {config.timeout_minutes}
                steps:
                  - uses: actions/checkout@v4
                  - name: Run BreadMind Code Review
                    env:
                      BREADMIND_MODEL: {config.model}
                    run: |
                      breadmind review --model $BREADMIND_MODEL
        """)

    def _render_pr_description(self, config: ActionConfig) -> str:
        return dedent(f"""\
            name: BreadMind PR Description
            on:
              {config.trigger}:
                types: [opened]
            jobs:
              describe:
                runs-on: ubuntu-latest
                timeout-minutes: {config.timeout_minutes}
                steps:
                  - uses: actions/checkout@v4
                  - name: Generate PR Description
                    env:
                      BREADMIND_MODEL: {config.model}
                    run: |
                      breadmind pr-describe --model $BREADMIND_MODEL
        """)

    def _render_test_generation(self, config: ActionConfig) -> str:
        return dedent(f"""\
            name: BreadMind Test Generation
            on:
              {config.trigger}:
                types: [opened, synchronize]
            jobs:
              generate-tests:
                runs-on: ubuntu-latest
                timeout-minutes: {config.timeout_minutes}
                steps:
                  - uses: actions/checkout@v4
                  - name: Generate Tests
                    env:
                      BREADMIND_MODEL: {config.model}
                    run: |
                      breadmind generate-tests --model $BREADMIND_MODEL
        """)

    def _render_dependency_audit(self, config: ActionConfig) -> str:
        trigger = config.trigger
        if trigger == "pull_request":
            trigger = "schedule"
        return dedent(f"""\
            name: BreadMind Dependency Audit
            on:
              {trigger}:
                - cron: '0 8 * * 1'
            jobs:
              audit:
                runs-on: ubuntu-latest
                timeout-minutes: {config.timeout_minutes}
                steps:
                  - uses: actions/checkout@v4
                  - name: Audit Dependencies
                    env:
                      BREADMIND_MODEL: {config.model}
                    run: |
                      breadmind audit-deps --model $BREADMIND_MODEL
        """)
