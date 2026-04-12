"""Tests for auth profile rotation."""
from __future__ import annotations

import time


from breadmind.llm.factory import AuthProfile, AuthRotator


def test_get_current_profile():
    """Should return the current active profile."""
    profiles = [
        AuthProfile(key="key1", name="profile1"),
        AuthProfile(key="key2", name="profile2"),
    ]
    rotator = AuthRotator(profiles)

    current = rotator.get_current()
    assert current is not None
    assert current.key == "key1"
    assert current.name == "profile1"


def test_report_failure_advances():
    """report_failure should mark current as failed and advance to next."""
    profiles = [
        AuthProfile(key="key1", name="p1"),
        AuthProfile(key="key2", name="p2"),
    ]
    rotator = AuthRotator(profiles)

    next_profile = rotator.report_failure(cooldown_seconds=60)
    assert next_profile is not None
    assert next_profile.key == "key2"

    # Original profile should be in cooldown
    assert profiles[0].failure_count == 1
    assert profiles[0].cooldown_until > time.time()


def test_all_in_cooldown_returns_none():
    """get_current should return None when all profiles are in cooldown."""
    profiles = [
        AuthProfile(key="key1", cooldown_until=time.time() + 3600),
        AuthProfile(key="key2", cooldown_until=time.time() + 3600),
    ]
    rotator = AuthRotator(profiles)

    current = rotator.get_current()
    assert current is None


def test_report_success_resets_count():
    """report_success should reset failure count for current profile."""
    profiles = [
        AuthProfile(key="key1", failure_count=5),
    ]
    rotator = AuthRotator(profiles)

    rotator.report_success()
    assert profiles[0].failure_count == 0


def test_active_count():
    """active_count should reflect how many profiles are available."""
    now = time.time()
    profiles = [
        AuthProfile(key="key1"),  # active (cooldown_until=0)
        AuthProfile(key="key2", cooldown_until=now + 3600),  # in cooldown
        AuthProfile(key="key3"),  # active
    ]
    rotator = AuthRotator(profiles)

    assert rotator.active_count == 2
