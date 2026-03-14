import pytest
from breadmind.core.safety import SafetyGuard, SafetyResult

@pytest.fixture
def guard():
    return SafetyGuard(
        blacklist={"test": ["dangerous_action"]},
        require_approval=["needs_approval"],
    )

def test_auto_allow(guard):
    result = guard.check("safe_action", {}, user="test_user", channel="test")
    assert result == SafetyResult.ALLOW

def test_blacklist_deny(guard):
    result = guard.check("dangerous_action", {}, user="test_user", channel="test")
    assert result == SafetyResult.DENY

def test_require_approval(guard):
    result = guard.check("needs_approval", {}, user="test_user", channel="test")
    assert result == SafetyResult.REQUIRE_APPROVAL

def test_flatten_blacklist(guard):
    assert "dangerous_action" in guard._flat_blacklist
