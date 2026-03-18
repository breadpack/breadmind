import pytest
from datetime import datetime, timedelta, timezone
from breadmind.core.safety import SafetyGuard, SafetyResult
from breadmind.memory.working import WorkingMemory
from breadmind.llm.base import LLMMessage

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

def test_cooldown_allows_first_call(guard):
    assert guard.check_cooldown("target1", "action1") is True

def test_cooldown_blocks_repeat(guard):
    guard.check_cooldown("target1", "action1")
    assert guard.check_cooldown("target1", "action1") is False

def test_cooldown_different_targets(guard):
    guard.check_cooldown("target1", "action1")
    assert guard.check_cooldown("target2", "action1") is True

def test_cooldown_expires():
    guard = SafetyGuard()
    guard.check_cooldown("t", "a", cooldown_minutes=0)
    # With 0 minutes, next call should be allowed immediately
    assert guard.check_cooldown("t", "a", cooldown_minutes=0) is True


# --- User permissions tests ---

def test_user_permissions_allowed_user():
    guard = SafetyGuard(
        user_permissions={"alice": ["tool_a", "tool_b"]},
    )
    result = guard.check("tool_a", {}, user="alice", channel="test")
    assert result == SafetyResult.ALLOW

def test_user_permissions_disallowed_user():
    guard = SafetyGuard(
        user_permissions={"alice": ["tool_a"]},
    )
    result = guard.check("tool_a", {}, user="bob", channel="test")
    assert result == SafetyResult.DENY

def test_user_permissions_user_tool_not_in_list():
    guard = SafetyGuard(
        user_permissions={"alice": ["tool_a"]},
    )
    result = guard.check("tool_b", {}, user="alice", channel="test")
    assert result == SafetyResult.DENY

def test_user_permissions_admin_bypasses_all():
    guard = SafetyGuard(
        user_permissions={"alice": ["tool_a"]},
        admin_users=["superadmin"],
    )
    # superadmin is not in user_permissions but should bypass
    result = guard.check("tool_a", {}, user="superadmin", channel="test")
    assert result == SafetyResult.ALLOW

def test_user_permissions_admin_bypasses_blacklist():
    guard = SafetyGuard(
        blacklist={"test": ["dangerous_action"]},
        admin_users=["superadmin"],
    )
    result = guard.check("dangerous_action", {}, user="superadmin", channel="test")
    assert result == SafetyResult.ALLOW

def test_user_permissions_empty_dict_no_restriction():
    guard = SafetyGuard(
        user_permissions={},
    )
    result = guard.check("any_tool", {}, user="anyone", channel="test")
    assert result == SafetyResult.ALLOW


# --- Datetime timezone-aware tests ---

def test_cooldown_uses_timezone_aware_utc():
    guard = SafetyGuard()
    guard.check_cooldown("t", "a")
    key = "t:a"
    stored = guard._cooldowns[key]
    assert stored.tzinfo is not None
    assert stored.tzinfo == timezone.utc


# --- Session timeout tests ---

def test_session_timeout_creates_fresh():
    memory = WorkingMemory(session_timeout_minutes=1)
    session = memory.get_or_create_session("s1", user="u", channel="c")
    memory.add_message("s1", LLMMessage(role="user", content="old message"))
    assert len(memory.get_messages("s1")) == 1

    # Simulate expiration by backdating last_active
    session.last_active = datetime.now(timezone.utc) - timedelta(minutes=2)

    # Should get a fresh session
    new_session = memory.get_or_create_session("s1", user="u", channel="c")
    assert len(new_session.messages) == 0


def test_session_not_expired():
    memory = WorkingMemory(session_timeout_minutes=30)
    memory.get_or_create_session("s1", user="u", channel="c")
    memory.add_message("s1", LLMMessage(role="user", content="message"))

    # Should keep existing session
    same_session = memory.get_or_create_session("s1", user="u", channel="c")
    assert len(same_session.messages) == 1


def test_cleanup_expired():
    memory = WorkingMemory(session_timeout_minutes=1)
    s1 = memory.get_or_create_session("s1")
    memory.get_or_create_session("s2")

    # Expire s1 only
    s1.last_active = datetime.now(timezone.utc) - timedelta(minutes=2)

    removed = memory.cleanup_expired()
    assert "s1" in removed
    assert "s2" not in removed
    assert "s1" not in memory.list_sessions()
    assert "s2" in memory.list_sessions()


def test_cleanup_no_expired():
    memory = WorkingMemory(session_timeout_minutes=30)
    memory.get_or_create_session("s1")
    removed = memory.cleanup_expired()
    assert removed == []


# --- Dynamic update tests ---

def test_update_blacklist_replaces():
    guard = SafetyGuard(blacklist={"old": ["old_tool"]})
    guard.update_blacklist({"new_cat": ["new_tool_a", "new_tool_b"]})
    assert guard._blacklist == {"new_cat": ["new_tool_a", "new_tool_b"]}
    assert guard._flat_blacklist == {"new_tool_a", "new_tool_b"}
    assert "old_tool" not in guard._flat_blacklist
    # Verify check behavior
    assert guard.check("new_tool_a", {}, user="u", channel="c") == SafetyResult.DENY
    assert guard.check("old_tool", {}, user="u", channel="c") == SafetyResult.ALLOW


def test_update_require_approval_replaces():
    guard = SafetyGuard(require_approval=["old_tool"])
    guard.update_require_approval(["new_tool_x", "new_tool_y"])
    assert guard._require_approval == {"new_tool_x", "new_tool_y"}
    assert guard.check("new_tool_x", {}, user="u", channel="c") == SafetyResult.REQUIRE_APPROVAL
    assert guard.check("old_tool", {}, user="u", channel="c") == SafetyResult.ALLOW


def test_update_user_permissions():
    guard = SafetyGuard(
        user_permissions={"alice": ["tool_a"]},
        admin_users=["old_admin"],
    )
    guard.update_user_permissions(
        {"bob": ["tool_b", "tool_c"]},
        admins=["new_admin"],
    )
    assert guard._user_permissions == {"bob": ["tool_b", "tool_c"]}
    assert guard._admin_users == ["new_admin"]
    # bob can use tool_b
    assert guard.check("tool_b", {}, user="bob", channel="c") == SafetyResult.ALLOW
    # alice no longer has permissions
    assert guard.check("tool_a", {}, user="alice", channel="c") == SafetyResult.DENY
    # new_admin bypasses
    assert guard.check("anything", {}, user="new_admin", channel="c") == SafetyResult.ALLOW


def test_update_user_permissions_no_admins():
    guard = SafetyGuard(admin_users=["keep_admin"])
    guard.update_user_permissions({"user1": ["tool1"]})
    # admins should remain unchanged when not passed
    assert guard._admin_users == ["keep_admin"]


def test_get_config_complete():
    guard = SafetyGuard(
        blacklist={"k8s": ["delete_ns"]},
        require_approval=["shell_exec"],
        user_permissions={"alice": ["tool_a"]},
        admin_users=["admin1"],
    )
    config = guard.get_config()
    assert config["blacklist"] == {"k8s": ["delete_ns"]}
    assert config["require_approval"] == ["shell_exec"]
    assert config["user_permissions"] == {"alice": ["tool_a"]}
    assert config["admin_users"] == ["admin1"]


def test_get_config_empty():
    guard = SafetyGuard()
    config = guard.get_config()
    assert config["blacklist"] == {}
    assert config["require_approval"] == []
    assert config["user_permissions"] == {}
    assert config["admin_users"] == []


def test_session_last_active_updates():
    memory = WorkingMemory()
    session = memory.get_or_create_session("s1")
    first_active = session.last_active

    # Adding a message should update last_active
    memory.add_message("s1", LLMMessage(role="user", content="hi"))
    assert session.last_active >= first_active
