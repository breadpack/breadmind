"""Tests for cron job tool allowlists."""
from __future__ import annotations

import pytest

from breadmind.core.cron_allowlist import CronAllowlistManager, CronToolPolicy


@pytest.fixture
def manager() -> CronAllowlistManager:
    return CronAllowlistManager()


# --- CronToolPolicy ---


def test_policy_deny_takes_precedence():
    policy = CronToolPolicy(
        job_id="j1",
        allowed_tools=["shell_*"],
        denied_tools=["shell_exec"],
    )
    assert policy.is_allowed("shell_exec") is False
    assert policy.is_allowed("shell_read") is True


def test_policy_empty_allowed_permits_all():
    policy = CronToolPolicy(job_id="j1", allowed_tools=[], denied_tools=[])
    assert policy.is_allowed("anything") is True
    assert policy.is_allowed("shell_exec") is True


def test_policy_allowed_restricts():
    policy = CronToolPolicy(
        job_id="j1",
        allowed_tools=["file_*", "http_get"],
        denied_tools=[],
    )
    assert policy.is_allowed("file_read") is True
    assert policy.is_allowed("file_write") is True
    assert policy.is_allowed("http_get") is True
    assert policy.is_allowed("shell_exec") is False


def test_policy_denied_only():
    policy = CronToolPolicy(
        job_id="j1",
        allowed_tools=[],
        denied_tools=["shell_*"],
    )
    assert policy.is_allowed("shell_exec") is False
    assert policy.is_allowed("file_read") is True


# --- CronAllowlistManager ---


def test_set_and_get_policy(manager: CronAllowlistManager):
    policy = manager.set_policy("job1", allowed=["file_*"], denied=["file_delete"])
    assert policy.job_id == "job1"
    assert manager.get_policy("job1") is policy
    assert manager.get_policy("nonexistent") is None


def test_check_tool_no_policy_allows(manager: CronAllowlistManager):
    assert manager.check_tool("no_policy_job", "shell_exec") is True


def test_check_tool_with_policy(manager: CronAllowlistManager):
    manager.set_policy("job1", allowed=["file_*"], denied=["file_delete"])
    assert manager.check_tool("job1", "file_read") is True
    assert manager.check_tool("job1", "file_delete") is False
    assert manager.check_tool("job1", "shell_exec") is False


def test_filter_tools(manager: CronAllowlistManager):
    manager.set_policy("job1", allowed=["file_*", "http_*"], denied=["http_post"])
    tools = ["file_read", "file_write", "shell_exec", "http_get", "http_post"]
    filtered = manager.filter_tools("job1", tools)
    assert filtered == ["file_read", "file_write", "http_get"]


def test_filter_tools_no_policy(manager: CronAllowlistManager):
    tools = ["shell_exec", "file_read"]
    filtered = manager.filter_tools("no_policy", tools)
    assert filtered == tools


def test_remove_policy(manager: CronAllowlistManager):
    manager.set_policy("job1", allowed=["file_*"])
    assert manager.remove_policy("job1") is True
    assert manager.remove_policy("job1") is False
    assert manager.get_policy("job1") is None


def test_list_policies(manager: CronAllowlistManager):
    manager.set_policy("job1", allowed=["file_*"])
    manager.set_policy("job2", denied=["shell_*"])
    policies = manager.list_policies()
    assert len(policies) == 2
    ids = {p.job_id for p in policies}
    assert ids == {"job1", "job2"}


def test_set_policy_overwrites(manager: CronAllowlistManager):
    manager.set_policy("job1", allowed=["file_*"])
    manager.set_policy("job1", allowed=["shell_*"])
    policy = manager.get_policy("job1")
    assert policy is not None
    assert policy.allowed_tools == ["shell_*"]
