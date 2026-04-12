"""Tests for session reset policies."""
from __future__ import annotations

import time
from unittest.mock import patch


from breadmind.core.session_policy import (
    SessionPolicyManager,
    SessionResetPolicy,
)


def test_create_new_session():
    """Should create a new session when none exists."""
    mgr = SessionPolicyManager()
    session, is_new = mgr.get_or_create_session("sess1", "slack")
    assert is_new is True
    assert session.session_id == "sess1"
    assert session.channel == "slack"
    assert session.message_count == 0


def test_reuse_active_session():
    """Should reuse an active session that hasn't expired."""
    mgr = SessionPolicyManager()
    session1, is_new1 = mgr.get_or_create_session("sess1", "slack")
    assert is_new1 is True

    session2, is_new2 = mgr.get_or_create_session("sess1", "slack")
    assert is_new2 is False
    assert session2 is session1


def test_idle_reset():
    """Should reset session after idle timeout."""
    policy = SessionResetPolicy(idle_reset_minutes=10)
    mgr = SessionPolicyManager(default_policy=policy)

    session1, _ = mgr.get_or_create_session("sess1", "slack")

    # Simulate idle by setting last_activity in the past
    session1.last_activity = time.time() - 700  # 11+ minutes ago

    session2, is_new = mgr.get_or_create_session("sess1", "slack")
    assert is_new is True
    assert session2 is not session1


def test_daily_reset():
    """Should reset session after daily reset time."""
    import datetime

    policy = SessionResetPolicy(daily_reset_hour=4)
    mgr = SessionPolicyManager(default_policy=policy)

    session1, _ = mgr.get_or_create_session("sess1", "slack")

    # Simulate: session created yesterday, now is after 4 AM
    session1.created_at = time.time() - 86400  # 24 hours ago
    now_mock = datetime.datetime.now().replace(hour=5)  # 5 AM

    with patch("breadmind.core.session_policy.datetime") as mock_dt:
        mock_dt.datetime.fromtimestamp = datetime.datetime.fromtimestamp
        mock_dt.datetime.now.return_value = now_mock

        session2, is_new = mgr.get_or_create_session("sess1", "slack")
        assert is_new is True


def test_per_channel_policy():
    """Per-channel policies should override default."""
    default = SessionResetPolicy(idle_reset_minutes=30)
    discord_policy = SessionResetPolicy(idle_reset_minutes=5)
    mgr = SessionPolicyManager(
        default_policy=default,
        per_channel={"discord": discord_policy},
    )

    # Slack session: 10min idle should not reset (default=30min)
    s1, _ = mgr.get_or_create_session("s1", "slack")
    s1.last_activity = time.time() - 600  # 10 min
    s1_again, is_new = mgr.get_or_create_session("s1", "slack")
    assert is_new is False

    # Discord session: 10min idle should reset (policy=5min)
    s2, _ = mgr.get_or_create_session("s2", "discord")
    s2.last_activity = time.time() - 600  # 10 min
    s2_again, is_new = mgr.get_or_create_session("s2", "discord")
    assert is_new is True


def test_record_activity():
    """record_activity should update last_activity and message_count."""
    mgr = SessionPolicyManager()
    session, _ = mgr.get_or_create_session("sess1", "slack")
    old_activity = session.last_activity

    time.sleep(0.01)
    mgr.record_activity("sess1")

    assert session.last_activity > old_activity
    assert session.message_count == 1

    mgr.record_activity("sess1")
    assert session.message_count == 2


def test_cleanup_expired():
    """cleanup_expired should remove idle sessions."""
    policy = SessionResetPolicy(idle_reset_minutes=1)
    mgr = SessionPolicyManager(default_policy=policy)

    s1, _ = mgr.get_or_create_session("s1", "slack")
    s2, _ = mgr.get_or_create_session("s2", "discord")

    # Make s1 idle
    s1.last_activity = time.time() - 120  # 2 min ago

    removed = mgr.cleanup_expired()
    assert removed == 1
    assert mgr.get_session_info("s1") is None
    assert mgr.get_session_info("s2") is not None
