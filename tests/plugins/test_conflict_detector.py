"""Tests for conflict detector."""
from __future__ import annotations

from breadmind.plugins.conflict_detector import (
    Conflict,
    ConflictDetector,
    ConflictReport,
    ConflictType,
)


# ── tool conflicts ──────────────────────────────────────────────────


def test_no_conflicts_when_unique():
    det = ConflictDetector()
    det.register_tools("builtin", ["shell", "file_read"])
    det.register_tools("plugin:github", ["github_pr", "github_issue"])
    report = det.detect_all()
    assert len(report.conflicts) == 0


def test_tool_name_collision_warning():
    det = ConflictDetector()
    det.register_tools("plugin:a", ["deploy"])
    det.register_tools("plugin:b", ["deploy"])
    report = det.detect_all()
    assert len(report.conflicts) == 1
    c = report.conflicts[0]
    assert c.type == ConflictType.TOOL_NAME
    assert c.name == "deploy"
    assert c.severity == "warning"
    assert set(c.sources) == {"plugin:a", "plugin:b"}


def test_mcp_shadowing_builtin_is_error():
    det = ConflictDetector()
    det.register_tools("builtin", ["shell"])
    det.register_tools("mcp:custom", ["shell"])
    report = det.detect_all()
    assert report.has_errors is True
    assert report.error_count == 1
    c = report.conflicts[0]
    assert c.type == ConflictType.MCP_TOOL
    assert c.severity == "error"


def test_multiple_tool_conflicts():
    det = ConflictDetector()
    det.register_tools("builtin", ["read", "write"])
    det.register_tools("plugin:x", ["read"])
    det.register_tools("mcp:y", ["write"])
    report = det.detect_all()
    assert len(report.conflicts) == 2
    # "write" conflict is MCP vs builtin -> error
    mcp_conflicts = [c for c in report.conflicts if c.type == ConflictType.MCP_TOOL]
    assert len(mcp_conflicts) == 1
    assert mcp_conflicts[0].name == "write"


# ── skill conflicts ─────────────────────────────────────────────────


def test_skill_name_collision():
    det = ConflictDetector()
    det.register_skills("plugin:a", ["deploy"])
    det.register_skills("plugin:b", ["deploy"])
    report = det.detect_all()
    skill_conflicts = [c for c in report.conflicts if c.type == ConflictType.SKILL_NAME]
    assert len(skill_conflicts) == 1
    assert skill_conflicts[0].name == "deploy"


# ── keyword conflicts ───────────────────────────────────────────────


def test_keyword_overlap():
    det = ConflictDetector()
    det.register_keywords("deploy-skill", ["deploy", "release"])
    det.register_keywords("cd-skill", ["deploy", "ship"])
    report = det.detect_all()
    kw_conflicts = [c for c in report.conflicts if c.type == ConflictType.TRIGGER_KEYWORD]
    assert len(kw_conflicts) == 1
    assert kw_conflicts[0].name == "deploy"
    assert set(kw_conflicts[0].sources) == {"deploy-skill", "cd-skill"}


def test_keyword_normalization():
    det = ConflictDetector()
    det.register_keywords("a", ["Deploy"])
    det.register_keywords("b", ["  deploy  "])
    report = det.detect_all()
    kw_conflicts = [c for c in report.conflicts if c.type == ConflictType.TRIGGER_KEYWORD]
    assert len(kw_conflicts) == 1


# ── check_before_install ────────────────────────────────────────────


def test_check_before_install_no_conflict():
    det = ConflictDetector()
    det.register_tools("builtin", ["shell"])
    report = det.check_before_install("new-plugin", "plugin:new", tool_names=["new_tool"])
    assert len(report.conflicts) == 0


def test_check_before_install_detects_tool_conflict():
    det = ConflictDetector()
    det.register_tools("builtin", ["shell"])
    report = det.check_before_install("bad", "mcp:bad", tool_names=["shell"])
    assert report.has_errors is True
    assert report.error_count == 1


def test_check_before_install_detects_skill_conflict():
    det = ConflictDetector()
    det.register_skills("plugin:a", ["summarize"])
    report = det.check_before_install("b", "plugin:b", skill_names=["summarize"])
    assert report.warning_count == 1


def test_check_before_install_does_not_modify_registry():
    det = ConflictDetector()
    det.register_tools("builtin", ["shell"])
    det.check_before_install("new", "plugin:new", tool_names=["shell", "extra"])
    # Registry should still only have builtin
    assert det._tool_registry["shell"] == ["builtin"]
    assert "extra" not in det._tool_registry


# ── unregister / clear ──────────────────────────────────────────────


def test_unregister_source():
    det = ConflictDetector()
    det.register_tools("plugin:a", ["t1", "t2"])
    det.register_tools("builtin", ["t1"])
    det.register_skills("plugin:a", ["s1"])
    det.unregister_source("plugin:a")
    assert det._tool_registry["t1"] == ["builtin"]
    assert "t2" not in det._tool_registry
    assert "s1" not in det._skill_registry


def test_clear():
    det = ConflictDetector()
    det.register_tools("a", ["t"])
    det.register_skills("a", ["s"])
    det.register_keywords("sk", ["kw"])
    det.clear()
    assert det._tool_registry == {}
    assert det._skill_registry == {}
    assert det._keyword_registry == {}


# ── ConflictReport properties ───────────────────────────────────────


def test_empty_report():
    report = ConflictReport()
    assert report.has_errors is False
    assert report.error_count == 0
    assert report.warning_count == 0


def test_report_mixed_severities():
    report = ConflictReport(conflicts=[
        Conflict(type=ConflictType.TOOL_NAME, name="a", sources=["x", "y"], severity="warning"),
        Conflict(type=ConflictType.MCP_TOOL, name="b", sources=["x", "y"], severity="error"),
        Conflict(type=ConflictType.TOOL_NAME, name="c", sources=["x", "y"], severity="warning"),
    ])
    assert report.has_errors is True
    assert report.error_count == 1
    assert report.warning_count == 2


def test_duplicate_source_registration_idempotent():
    det = ConflictDetector()
    det.register_tools("builtin", ["shell"])
    det.register_tools("builtin", ["shell"])
    assert det._tool_registry["shell"] == ["builtin"]
    report = det.detect_all()
    assert len(report.conflicts) == 0
