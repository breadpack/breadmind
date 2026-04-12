"""Tests for the adversarial code reviewer."""
from __future__ import annotations


from breadmind.core.adversarial_review import (
    AdversarialReviewer,
    IssueSeverity,
    ReviewIssue,
    ReviewResult,
)


def test_clean_code_approved():
    reviewer = AdversarialReviewer()
    result = reviewer.review([{"path": "clean.py", "content": "x = 1\n"}])
    assert result.approved is True
    assert result.critical_count == 0


def test_detects_hardcoded_secret():
    code = 'api_key = "sk-abcdefghijklmnopqrstuvwxyz1234567890"\n'
    reviewer = AdversarialReviewer()
    issues = reviewer.review_file("config.py", code)
    security = [i for i in issues if i.category == "security"]
    assert len(security) >= 1
    assert security[0].severity == IssueSeverity.CRITICAL


def test_detects_eval():
    code = "result = eval(user_input)\n"
    reviewer = AdversarialReviewer()
    issues = reviewer.review_file("handler.py", code)
    security = [i for i in issues if i.category == "security"]
    assert any("eval" in i.message.lower() for i in security)
    assert security[0].severity == IssueSeverity.CRITICAL


def test_detects_empty_except():
    code = "try:\n    foo()\nexcept:\n    pass\n"
    reviewer = AdversarialReviewer()
    issues = reviewer.review_file("app.py", code)
    logic = [i for i in issues if i.category == "logic"]
    assert any("except" in i.message.lower() for i in logic)
    assert logic[0].severity == IssueSeverity.WARNING


def test_detects_todo_fixme():
    code = "x = 1  # TODO fix this later\n# FIXME: broken\n"
    reviewer = AdversarialReviewer()
    issues = reviewer.review_file("app.py", code)
    todos = [i for i in issues if "TODO" in i.message or "FIXME" in i.message]
    assert len(todos) == 2
    assert all(i.severity == IssueSeverity.INFO for i in todos)


def test_detects_long_function():
    lines = ["def big_func():\n"] + ["    x = 1\n"] * 60
    code = "".join(lines)
    reviewer = AdversarialReviewer()
    issues = reviewer.review_file("big.py", code)
    style = [i for i in issues if i.category == "style"]
    assert len(style) >= 1
    assert "big_func" in style[0].message


def test_detects_blocking_in_async():
    code = (
        "import time\n"
        "async def handler():\n"
        "    time.sleep(5)\n"
        "    return 1\n"
    )
    reviewer = AdversarialReviewer()
    issues = reviewer.review_file("server.py", code)
    perf = [i for i in issues if i.category == "performance"]
    assert len(perf) >= 1
    assert perf[0].severity == IssueSeverity.WARNING


def test_review_not_approved_on_critical():
    code = 'token = "ghp_AAAAAAAAAAAAAAAAAAAABBBBBBBBBBBBBBBBBB"\nresult = eval(x)\n'
    reviewer = AdversarialReviewer()
    result = reviewer.review([{"path": "bad.py", "content": code}])
    assert result.approved is False
    assert result.critical_count >= 1


def test_custom_rule():
    def check_print(path: str, content: str) -> list[ReviewIssue]:
        issues = []
        for i, line in enumerate(content.split("\n"), 1):
            if "print(" in line:
                issues.append(
                    ReviewIssue(
                        severity=IssueSeverity.INFO,
                        category="style",
                        message="print() found",
                        file_path=path,
                        line=i,
                    )
                )
        return issues

    reviewer = AdversarialReviewer()
    reviewer.add_rule("style", check_print)
    issues = reviewer.review_file("debug.py", "print('hello')\n")
    assert any("print" in i.message.lower() for i in issues)


def test_severity_threshold_filters():
    """When threshold is CRITICAL, only critical issues are returned."""
    code = "x = 1  # TODO fix\n"
    reviewer = AdversarialReviewer(severity_threshold=IssueSeverity.CRITICAL)
    result = reviewer.review([{"path": "a.py", "content": code}])
    assert all(i.severity == IssueSeverity.CRITICAL for i in result.issues)


def test_review_result_properties():
    result = ReviewResult(
        approved=False,
        issues=[
            ReviewIssue(severity=IssueSeverity.CRITICAL, category="security", message="a"),
            ReviewIssue(severity=IssueSeverity.WARNING, category="logic", message="b"),
            ReviewIssue(severity=IssueSeverity.WARNING, category="logic", message="c"),
            ReviewIssue(severity=IssueSeverity.INFO, category="style", message="d"),
        ],
    )
    assert result.critical_count == 1
    assert result.warning_count == 2
