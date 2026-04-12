"""Tests for granular permission pattern matching in SafetyGuard."""
import pytest
from breadmind.plugins.builtin.safety.guard import SafetyGuard


@pytest.fixture
def guard_with_rules():
    """Create a SafetyGuard with permission rules."""
    rules = [
        {"pattern": "shell_exec(npm test:*)", "action": "allow", "scope": "session"},
        {"pattern": "shell_exec(rm -rf *)", "action": "deny", "scope": "always"},
        {"pattern": "file_write(*.log)", "action": "ask", "scope": "once"},
        {"pattern": "k8s_*", "action": "allow", "scope": "session"},
    ]
    return SafetyGuard(autonomy="confirm-destructive", permission_rules=rules)


def test_pattern_matching_tool_and_args(guard_with_rules):
    verdict = guard_with_rules.check("shell_exec", {"command": "npm test:unit"})
    assert verdict.allowed is True
    assert verdict.needs_approval is False


def test_pattern_deny_overrides(guard_with_rules):
    verdict = guard_with_rules.check("shell_exec", {"command": "rm -rf /"})
    assert verdict.allowed is False
    assert "Denied by permission rule" in verdict.reason


def test_pattern_allow_bypasses_autonomy():
    rules = [{"pattern": "shell_exec(npm test:*)", "action": "allow"}]
    guard = SafetyGuard(autonomy="confirm-all", permission_rules=rules)
    verdict = guard.check("shell_exec", {"command": "npm test:integration"})
    assert verdict.allowed is True
    assert verdict.needs_approval is False


def test_pattern_ask_requires_approval(guard_with_rules):
    verdict = guard_with_rules.check("file_write", {"path": "app.log"})
    assert verdict.allowed is True
    assert verdict.needs_approval is True
    assert "Permission rule requires approval" in verdict.reason


def test_no_matching_rule_falls_through():
    rules = [{"pattern": "shell_exec(npm *)", "action": "allow"}]
    guard = SafetyGuard(autonomy="confirm-all", permission_rules=rules)
    verdict = guard.check("file_read", {"path": "/etc/passwd"})
    # No rule matched, falls through to confirm-all autonomy
    assert verdict.needs_approval is True


def test_wildcard_tool_pattern(guard_with_rules):
    verdict = guard_with_rules.check("k8s_pods_list", {"namespace": "default"})
    assert verdict.allowed is True
    assert verdict.needs_approval is False


def test_scope_field_parsed():
    rules = [
        {"pattern": "shell_exec(echo *)", "action": "allow", "scope": "always"},
        {"pattern": "web_fetch", "action": "ask", "scope": "once"},
    ]
    guard = SafetyGuard(permission_rules=rules)
    # Verify compiled rules have correct scope
    assert guard._compiled_rules[0].scope == "always"
    assert guard._compiled_rules[1].scope == "once"
    assert guard._compiled_rules[0].tool_pattern == "shell_exec"
    assert guard._compiled_rules[0].arg_pattern == "echo *"
    assert guard._compiled_rules[1].tool_pattern == "web_fetch"
    assert guard._compiled_rules[1].arg_pattern == ""
