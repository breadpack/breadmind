"""Tests for the SafetyGuard audit log."""
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from breadmind.plugins.builtin.safety.audit import AuditEntry, AuditLog
from breadmind.plugins.builtin.safety.guard import SafetyGuard, SafetyVerdict


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_entry(
    *,
    user: str = "alice",
    tool_name: str = "shell_exec",
    verdict: str = "allow",
    reason: str = "",
    approved: bool | None = True,
    duration_ms: float = 1.0,
) -> AuditEntry:
    return AuditEntry(
        timestamp=datetime.now(timezone.utc),
        trace_id=None,
        user=user,
        tool_name=tool_name,
        arguments={"cmd": "ls"},
        verdict=verdict,
        reason=reason,
        approved=approved,
        duration_ms=duration_ms,
    )


# ── test_record_entry ────────────────────────────────────────────────────


def test_record_entry():
    log = AuditLog(max_entries=10)
    entry = _make_entry()
    log.record(entry)

    entries = log.get_entries()
    assert len(entries) == 1
    assert entries[0] is entry


# ── test_circular_buffer ─────────────────────────────────────────────────


def test_circular_buffer():
    log = AuditLog(max_entries=3)
    for i in range(5):
        log.record(_make_entry(user=f"user_{i}"))

    entries = log.get_entries(limit=100)
    assert len(entries) == 3
    # 가장 최신 항목이 먼저 반환
    assert entries[0].user == "user_4"
    assert entries[1].user == "user_3"
    assert entries[2].user == "user_2"


# ── test_get_entries_filter_by_user ──────────────────────────────────────


def test_get_entries_filter_by_user():
    log = AuditLog()
    log.record(_make_entry(user="alice"))
    log.record(_make_entry(user="bob"))
    log.record(_make_entry(user="alice"))

    entries = log.get_entries(user="alice")
    assert len(entries) == 2
    assert all(e.user == "alice" for e in entries)


# ── test_get_entries_filter_by_tool ──────────────────────────────────────


def test_get_entries_filter_by_tool():
    log = AuditLog()
    log.record(_make_entry(tool_name="shell_exec"))
    log.record(_make_entry(tool_name="file_write"))
    log.record(_make_entry(tool_name="shell_exec"))

    entries = log.get_entries(tool="shell_exec")
    assert len(entries) == 2
    assert all(e.tool_name == "shell_exec" for e in entries)


# ── test_get_entries_filter_by_verdict ───────────────────────────────────


def test_get_entries_filter_by_verdict():
    log = AuditLog()
    log.record(_make_entry(verdict="allow"))
    log.record(_make_entry(verdict="deny"))
    log.record(_make_entry(verdict="allow"))
    log.record(_make_entry(verdict="approve_required"))

    entries = log.get_entries(verdict="deny")
    assert len(entries) == 1
    assert entries[0].verdict == "deny"


# ── test_get_stats ───────────────────────────────────────────────────────


def test_get_stats():
    log = AuditLog()
    log.record(_make_entry(verdict="allow", tool_name="shell_exec"))
    log.record(_make_entry(verdict="allow", tool_name="file_read"))
    log.record(_make_entry(verdict="deny", tool_name="shell_exec"))
    log.record(_make_entry(verdict="deny", tool_name="shell_exec"))
    log.record(_make_entry(verdict="approve_required", tool_name="k8s_pods_delete"))

    stats = log.get_stats()
    assert stats["total"] == 5
    assert stats["allow"] == 2
    assert stats["deny"] == 2
    assert stats["approve_required"] == 1
    assert stats["allow_ratio"] == pytest.approx(0.4)
    assert stats["deny_ratio"] == pytest.approx(0.4)
    assert stats["approve_required_ratio"] == pytest.approx(0.2)
    assert stats["most_denied_tools"][0]["tool"] == "shell_exec"
    assert stats["most_denied_tools"][0]["count"] == 2


def test_get_stats_empty():
    log = AuditLog()
    stats = log.get_stats()
    assert stats["total"] == 0
    assert stats["allow_ratio"] == 0.0


# ── test_export_json ─────────────────────────────────────────────────────


def test_export_json():
    log = AuditLog()
    log.record(_make_entry(user="alice", tool_name="shell_exec", verdict="allow"))
    log.record(_make_entry(user="bob", tool_name="file_write", verdict="deny"))

    exported = log.export_json()
    data = json.loads(exported)
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["user"] == "alice"
    assert data[1]["verdict"] == "deny"
    # timestamp는 ISO 문자열이어야 함
    assert isinstance(data[0]["timestamp"], str)


# ── test_safety_guard_integration ────────────────────────────────────────


def test_safety_guard_integration():
    """SafetyGuard.check() 호출 시 audit_log에 자동 기록."""
    audit_log = AuditLog()
    guard = SafetyGuard(autonomy="auto", audit_log=audit_log)

    verdict = guard.check("shell_exec", {"cmd": "ls"}, user="alice")
    assert verdict.allowed is True

    entries = audit_log.get_entries()
    assert len(entries) == 1
    assert entries[0].tool_name == "shell_exec"
    assert entries[0].user == "alice"
    assert entries[0].verdict == "allow"
    assert entries[0].duration_ms >= 0


def test_safety_guard_integration_deny():
    """blocked pattern에 의한 deny가 감사 로그에 기록됨."""
    audit_log = AuditLog()
    guard = SafetyGuard(
        autonomy="confirm-destructive",
        blocked_patterns=["dangerous"],
        audit_log=audit_log,
    )

    verdict = guard.check("shell_exec", {"cmd": "dangerous command"}, user="bob")
    assert verdict.allowed is False

    entries = audit_log.get_entries()
    assert len(entries) == 1
    assert entries[0].verdict == "deny"
    assert entries[0].user == "bob"


def test_safety_guard_integration_approve_required():
    """needs_approval 판정이 approve_required로 기록됨."""
    audit_log = AuditLog()
    guard = SafetyGuard(
        autonomy="confirm-all",
        audit_log=audit_log,
    )

    verdict = guard.check("shell_exec", {"cmd": "ls"}, user="carol")
    assert verdict.needs_approval is True

    entries = audit_log.get_entries()
    assert len(entries) == 1
    assert entries[0].verdict == "approve_required"


# ── test_audit_log_disabled ──────────────────────────────────────────────


def test_audit_log_disabled():
    """audit_log=None 시 에러 없이 동작."""
    guard = SafetyGuard(autonomy="auto", audit_log=None)
    verdict = guard.check("shell_exec", {"cmd": "ls"})
    assert verdict.allowed is True


# ── test_clear ───────────────────────────────────────────────────────────


def test_clear():
    log = AuditLog()
    log.record(_make_entry())
    log.record(_make_entry())
    assert len(log.get_entries()) == 2

    log.clear()
    assert len(log.get_entries()) == 0

    stats = log.get_stats()
    assert stats["total"] == 0
