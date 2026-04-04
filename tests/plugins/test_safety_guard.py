import pytest
from breadmind.plugins.v2_builtin.safety.guard import SafetyGuard

@pytest.fixture
def guard_auto():
    return SafetyGuard(autonomy="auto", blocked_patterns=["rm -rf /", "mkfs"])

@pytest.fixture
def guard_destructive():
    return SafetyGuard(autonomy="confirm-destructive", blocked_patterns=["rm -rf /"])

@pytest.fixture
def guard_all():
    return SafetyGuard(autonomy="confirm-all")

def test_auto_allows_everything(guard_auto):
    v = guard_auto.check("shell_exec", {"command": "ls -la"})
    assert v.allowed is True
    assert v.needs_approval is False

def test_auto_blocks_blacklist(guard_auto):
    v = guard_auto.check("shell_exec", {"command": "rm -rf /"})
    assert v.allowed is False
    assert "blocked" in v.reason.lower()

def test_destructive_approves_safe(guard_destructive):
    v = guard_destructive.check("file_read", {"path": "/etc/hosts"})
    assert v.allowed is True
    assert v.needs_approval is False

def test_destructive_requires_approval_for_delete(guard_destructive):
    v = guard_destructive.check("shell_exec", {"command": "kubectl delete pod nginx"})
    assert v.needs_approval is True

def test_confirm_all_requires_approval_always(guard_all):
    v = guard_all.check("file_read", {"path": "/tmp/test"})
    assert v.needs_approval is True

def test_blocked_patterns_override_all_levels():
    guard = SafetyGuard(autonomy="auto", blocked_patterns=["dd if="])
    v = guard.check("shell_exec", {"command": "dd if=/dev/zero of=/dev/sda"})
    assert v.allowed is False

def test_custom_approve_required():
    guard = SafetyGuard(autonomy="confirm-destructive", approve_required=["web_search"])
    v = guard.check("web_search", {"query": "test"})
    assert v.needs_approval is True
