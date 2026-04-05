"""Validate skills before installation/use."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class ValidationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationIssue:
    severity: ValidationSeverity
    field: str
    message: str


@dataclass
class ValidationResult:
    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    score: float = 0.0  # 0-100 quality score

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.WARNING]


class SkillValidator:
    """Validates skill quality and safety before installation.

    Checks:
    - Required fields (name, description)
    - Description quality (length, specificity)
    - Prompt template safety (no injection patterns)
    - Trigger keyword quality (not too generic, not too many)
    - Content length limits
    - Duplicate detection
    """

    MAX_NAME_LENGTH = 100
    MAX_DESCRIPTION_LENGTH = 500
    MAX_TEMPLATE_LENGTH = 10000
    MAX_KEYWORDS = 20
    MIN_DESCRIPTION_LENGTH = 20

    DANGEROUS_PATTERNS = [
        r"ignore previous instructions",
        r"ignore all instructions",
        r"you are now",
        r"system prompt",
        r"<script",
        r"javascript:",
        r"eval\(",
        r"exec\(",
    ]

    GENERIC_KEYWORDS = frozenset({
        "help", "run", "do", "make", "get", "set", "the", "a", "an",
        "is", "it", "to", "and", "or", "of", "in", "on", "for",
    })

    def __init__(self, existing_skills: list[str] | None = None) -> None:
        self._existing = set(existing_skills or [])

    def validate(
        self,
        name: str,
        description: str = "",
        prompt_template: str = "",
        trigger_keywords: list[str] | None = None,
        content: str = "",
    ) -> ValidationResult:
        """Run all validation checks and return result with quality score."""
        issues: list[ValidationIssue] = []

        issues.extend(self._check_name(name))
        issues.extend(self._check_description(description))
        issues.extend(self._check_template(prompt_template))
        issues.extend(self._check_keywords(trigger_keywords or []))
        issues.extend(self._check_duplicates(name))

        # Check combined content length
        combined = prompt_template + content
        if len(combined) > self.MAX_TEMPLATE_LENGTH:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    field="content",
                    message=f"Combined content exceeds maximum length of {self.MAX_TEMPLATE_LENGTH} characters",
                )
            )

        has_errors = any(i.severity == ValidationSeverity.ERROR for i in issues)
        score = self._calculate_score(
            issues,
            has_description=bool(description),
            has_template=bool(prompt_template),
            has_keywords=bool(trigger_keywords),
        )

        return ValidationResult(valid=not has_errors, issues=issues, score=score)

    def _check_name(self, name: str) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not name or not name.strip():
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    field="name",
                    message="Name is required",
                )
            )
            return issues

        name = name.strip()
        if len(name) > self.MAX_NAME_LENGTH:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    field="name",
                    message=f"Name exceeds maximum length of {self.MAX_NAME_LENGTH} characters",
                )
            )

        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9 _\-\.]*$", name):
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    field="name",
                    message="Name should start with alphanumeric and contain only letters, digits, spaces, hyphens, underscores, or dots",
                )
            )

        return issues

    def _check_description(self, description: str) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not description or not description.strip():
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    field="description",
                    message="Description is required",
                )
            )
            return issues

        desc = description.strip()
        if len(desc) < self.MIN_DESCRIPTION_LENGTH:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    field="description",
                    message=f"Description is too short (minimum {self.MIN_DESCRIPTION_LENGTH} characters recommended)",
                )
            )

        if len(desc) > self.MAX_DESCRIPTION_LENGTH:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    field="description",
                    message=f"Description exceeds recommended maximum of {self.MAX_DESCRIPTION_LENGTH} characters",
                )
            )

        # Check for low-quality descriptions (all same word, etc.)
        words = desc.lower().split()
        unique_words = set(words)
        if len(words) >= 3 and len(unique_words) == 1:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    field="description",
                    message="Description appears to be low quality (repeated words)",
                )
            )

        return issues

    def _check_template(self, template: str) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not template:
            return issues

        if len(template) > self.MAX_TEMPLATE_LENGTH:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    field="prompt_template",
                    message=f"Template exceeds maximum length of {self.MAX_TEMPLATE_LENGTH} characters",
                )
            )

        # Check for prompt injection patterns
        template_lower = template.lower()
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, template_lower):
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        field="prompt_template",
                        message=f"Template contains potentially dangerous pattern: {pattern}",
                    )
                )

        return issues

    def _check_keywords(self, keywords: list[str]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not keywords:
            return issues

        if len(keywords) > self.MAX_KEYWORDS:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    field="trigger_keywords",
                    message=f"Too many keywords ({len(keywords)}). Maximum recommended: {self.MAX_KEYWORDS}",
                )
            )

        generic_found = [
            kw for kw in keywords if kw.lower() in self.GENERIC_KEYWORDS
        ]
        if generic_found:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    field="trigger_keywords",
                    message=f"Keywords contain generic terms that may cause false matches: {', '.join(generic_found)}",
                )
            )

        # Check for very short keywords
        short_kw = [kw for kw in keywords if len(kw) < 2]
        if short_kw:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    field="trigger_keywords",
                    message=f"Keywords contain very short terms: {', '.join(short_kw)}",
                )
            )

        # Check for duplicates
        seen: set[str] = set()
        dupes: list[str] = []
        for kw in keywords:
            lower = kw.lower()
            if lower in seen:
                dupes.append(kw)
            seen.add(lower)
        if dupes:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.INFO,
                    field="trigger_keywords",
                    message=f"Duplicate keywords found: {', '.join(dupes)}",
                )
            )

        return issues

    def _check_duplicates(self, name: str) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not name:
            return issues

        name_lower = name.lower().strip()
        for existing in self._existing:
            if existing.lower() == name_lower:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        field="name",
                        message=f"A skill with name '{existing}' already exists",
                    )
                )
                break

        # Check for similar names (simple edit-distance-like check)
        for existing in self._existing:
            existing_lower = existing.lower()
            if existing_lower == name_lower:
                continue  # Already handled above
            # Check if one is a substring of the other
            if (
                name_lower in existing_lower or existing_lower in name_lower
            ) and abs(len(name_lower) - len(existing_lower)) <= 3:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.WARNING,
                        field="name",
                        message=f"Name is very similar to existing skill '{existing}'",
                    )
                )
                break

        return issues

    def _calculate_score(
        self,
        issues: list[ValidationIssue],
        has_description: bool,
        has_template: bool,
        has_keywords: bool,
    ) -> float:
        """Calculate quality score 0-100 based on issues and completeness."""
        score = 100.0

        # Deductions for issues
        for issue in issues:
            if issue.severity == ValidationSeverity.ERROR:
                score -= 25.0
            elif issue.severity == ValidationSeverity.WARNING:
                score -= 10.0
            elif issue.severity == ValidationSeverity.INFO:
                score -= 2.0

        # Bonuses for completeness
        if not has_description:
            score -= 15.0
        if not has_template:
            score -= 10.0
        if not has_keywords:
            score -= 5.0

        return max(0.0, min(100.0, score))
