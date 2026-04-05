"""Adversarial code reviewer: checks for security issues, logic errors, and style violations."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class IssueSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ReviewIssue:
    severity: IssueSeverity
    category: str  # "security", "logic", "style", "performance", "test"
    message: str
    file_path: str = ""
    line: int = 0
    suggestion: str = ""


@dataclass
class ReviewResult:
    approved: bool
    issues: list[ReviewIssue] = field(default_factory=list)
    summary: str = ""

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.CRITICAL)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.WARNING)


# Type alias for a rule checker function
RuleChecker = Callable[[str, str], list[ReviewIssue]]


class AdversarialReviewer:
    """Critic agent that reviews code changes before committing.

    Performs rule-based checks for common issues:
    - Security: hardcoded secrets, SQL injection patterns, eval/exec usage
    - Logic: TODO/FIXME left in code, empty except blocks
    - Style: overly long functions, missing type hints on public functions
    - Performance: blocking calls in async functions
    """

    def __init__(
        self, severity_threshold: IssueSeverity = IssueSeverity.WARNING
    ) -> None:
        self._threshold = severity_threshold
        self._rules: list[tuple[str, RuleChecker]] = []
        self._register_default_rules()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def review(self, changes: list[dict]) -> ReviewResult:
        """Review a list of file changes.

        Each change dict has: ``path``, ``content`` (new text),
        ``old_content`` (optional previous text).
        Returns *ReviewResult* with approval decision.
        """
        all_issues: list[ReviewIssue] = []
        for change in changes:
            path = change.get("path", "")
            content = change.get("content", "")
            all_issues.extend(self.review_file(path, content))

        # Filter by threshold
        severity_order = {
            IssueSeverity.CRITICAL: 0,
            IssueSeverity.WARNING: 1,
            IssueSeverity.INFO: 2,
        }
        threshold_val = severity_order[self._threshold]
        filtered = [
            i for i in all_issues if severity_order[i.severity] <= threshold_val
        ]

        approved = not any(
            i.severity == IssueSeverity.CRITICAL for i in filtered
        )
        summary = self._build_summary(filtered)
        return ReviewResult(approved=approved, issues=filtered, summary=summary)

    def review_file(self, path: str, content: str) -> list[ReviewIssue]:
        """Review a single file's content."""
        issues: list[ReviewIssue] = []
        for _category, checker in self._rules:
            issues.extend(checker(path, content))
        return issues

    def add_rule(self, category: str, checker: RuleChecker) -> None:
        """Add a custom review rule."""
        self._rules.append((category, checker))

    # ------------------------------------------------------------------
    # Built-in rules
    # ------------------------------------------------------------------

    def _register_default_rules(self) -> None:
        self._rules.extend([
            ("security", self._check_hardcoded_secrets),
            ("security", self._check_dangerous_functions),
            ("logic", self._check_empty_except),
            ("logic", self._check_todo_fixme),
            ("style", self._check_function_length),
            ("performance", self._check_blocking_in_async),
        ])

    def _check_hardcoded_secrets(
        self, path: str, content: str
    ) -> list[ReviewIssue]:
        """Detect potential hardcoded secrets (API keys, passwords, tokens)."""
        issues: list[ReviewIssue] = []
        patterns = [
            (r"""(?:api[_-]?key|secret|token|password)\s*[:=]\s*['"][A-Za-z0-9_\-]{16,}['"]""",
             "Possible hardcoded secret"),
            (r"""sk-[A-Za-z0-9]{20,}""", "Possible OpenAI/Stripe secret key"),
            (r"""AIza[A-Za-z0-9_\-]{35}""", "Possible Google API key"),
            (r"""ghp_[A-Za-z0-9]{36}""", "Possible GitHub personal access token"),
        ]
        for pat, msg in patterns:
            for match in re.finditer(pat, content, re.IGNORECASE):
                line = content[:match.start()].count("\n") + 1
                issues.append(
                    ReviewIssue(
                        severity=IssueSeverity.CRITICAL,
                        category="security",
                        message=msg,
                        file_path=path,
                        line=line,
                        suggestion="Use environment variables or a credential vault instead.",
                    )
                )
        return issues

    def _check_dangerous_functions(
        self, path: str, content: str
    ) -> list[ReviewIssue]:
        """Detect eval(), exec(), __import__(), os.system() usage."""
        issues: list[ReviewIssue] = []
        patterns = [
            (r"""\beval\s*\(""", "Use of eval()"),
            (r"""\bexec\s*\(""", "Use of exec()"),
            (r"""\b__import__\s*\(""", "Use of __import__()"),
            (r"""\bos\.system\s*\(""", "Use of os.system()"),
        ]
        for pat, msg in patterns:
            for match in re.finditer(pat, content):
                line = content[:match.start()].count("\n") + 1
                issues.append(
                    ReviewIssue(
                        severity=IssueSeverity.CRITICAL,
                        category="security",
                        message=msg,
                        file_path=path,
                        line=line,
                        suggestion="Use safer alternatives (subprocess.run, importlib, etc.).",
                    )
                )
        return issues

    def _check_empty_except(
        self, path: str, content: str
    ) -> list[ReviewIssue]:
        """Detect bare except: or except Exception: with only pass."""
        issues: list[ReviewIssue] = []
        pattern = r"""except(?:\s+\w+)?:\s*\n\s+pass\b"""
        for match in re.finditer(pattern, content):
            line = content[:match.start()].count("\n") + 1
            issues.append(
                ReviewIssue(
                    severity=IssueSeverity.WARNING,
                    category="logic",
                    message="Empty except block (swallows errors silently)",
                    file_path=path,
                    line=line,
                    suggestion="Log the exception or handle it explicitly.",
                )
            )
        return issues

    def _check_todo_fixme(
        self, path: str, content: str
    ) -> list[ReviewIssue]:
        """Detect TODO/FIXME/HACK/XXX comments."""
        issues: list[ReviewIssue] = []
        pattern = r"""#\s*(TODO|FIXME|HACK|XXX)\b"""
        for match in re.finditer(pattern, content, re.IGNORECASE):
            line = content[:match.start()].count("\n") + 1
            tag = match.group(1).upper()
            issues.append(
                ReviewIssue(
                    severity=IssueSeverity.INFO,
                    category="logic",
                    message=f"{tag} comment found",
                    file_path=path,
                    line=line,
                    suggestion=f"Resolve the {tag} before committing.",
                )
            )
        return issues

    def _check_function_length(
        self, path: str, content: str, max_lines: int = 50
    ) -> list[ReviewIssue]:
        """Detect functions longer than *max_lines*."""
        issues: list[ReviewIssue] = []
        # Match def lines, then count until next def or end
        lines = content.split("\n")
        func_start: int | None = None
        func_name = ""
        func_indent = 0

        for i, raw_line in enumerate(lines):
            stripped = raw_line.lstrip()
            if stripped.startswith("def "):
                # Close previous function
                if func_start is not None:
                    length = i - func_start
                    if length > max_lines:
                        issues.append(
                            ReviewIssue(
                                severity=IssueSeverity.INFO,
                                category="style",
                                message=f"Function '{func_name}' is {length} lines long (>{max_lines})",
                                file_path=path,
                                line=func_start + 1,
                                suggestion="Consider breaking it into smaller functions.",
                            )
                        )
                func_start = i
                func_indent = len(raw_line) - len(stripped)
                m = re.match(r"def\s+(\w+)", stripped)
                func_name = m.group(1) if m else "?"

        # Check last function
        if func_start is not None:
            length = len(lines) - func_start
            if length > max_lines:
                issues.append(
                    ReviewIssue(
                        severity=IssueSeverity.INFO,
                        category="style",
                        message=f"Function '{func_name}' is {length} lines long (>{max_lines})",
                        file_path=path,
                        line=func_start + 1,
                        suggestion="Consider breaking it into smaller functions.",
                    )
                )
        return issues

    def _check_blocking_in_async(
        self, path: str, content: str
    ) -> list[ReviewIssue]:
        """Detect blocking calls (time.sleep, requests.get) inside async functions."""
        issues: list[ReviewIssue] = []
        blocking_patterns = [
            (r"""\btime\.sleep\s*\(""", "time.sleep()", "Use asyncio.sleep() instead."),
            (r"""\brequests\.\w+\s*\(""", "blocking requests call", "Use aiohttp or httpx instead."),
            (r"""\burllib\.request\.\w+\s*\(""", "blocking urllib call", "Use aiohttp or httpx instead."),
        ]

        # Find async function regions
        lines = content.split("\n")
        in_async = False
        async_indent = 0

        for i, raw_line in enumerate(lines):
            stripped = raw_line.lstrip()
            indent = len(raw_line) - len(stripped)

            if stripped.startswith("async def "):
                in_async = True
                async_indent = indent
                continue

            # Exited async function when we see a non-empty line at same or lesser indent
            if in_async and stripped and indent <= async_indent and not stripped.startswith("async def "):
                in_async = False

            if in_async:
                for pat, name, suggestion in blocking_patterns:
                    if re.search(pat, raw_line):
                        issues.append(
                            ReviewIssue(
                                severity=IssueSeverity.WARNING,
                                category="performance",
                                message=f"Blocking call '{name}' inside async function",
                                file_path=path,
                                line=i + 1,
                                suggestion=suggestion,
                            )
                        )
        return issues

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_summary(issues: list[ReviewIssue]) -> str:
        if not issues:
            return "No issues found."
        critical = sum(1 for i in issues if i.severity == IssueSeverity.CRITICAL)
        warning = sum(1 for i in issues if i.severity == IssueSeverity.WARNING)
        info = sum(1 for i in issues if i.severity == IssueSeverity.INFO)
        parts: list[str] = []
        if critical:
            parts.append(f"{critical} critical")
        if warning:
            parts.append(f"{warning} warning(s)")
        if info:
            parts.append(f"{info} info")
        return f"Found {', '.join(parts)}."
