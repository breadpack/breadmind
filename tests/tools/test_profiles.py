"""Tests for tool profiles and group shorthands."""
from __future__ import annotations

import pytest

from breadmind.tools.profiles import (
    PROFILES,
    ToolProfileManager,
)


@pytest.fixture
def manager() -> ToolProfileManager:
    return ToolProfileManager()


async def test_full_profile_allows_all(manager: ToolProfileManager):
    assert manager.is_allowed("shell_exec", "full") is True
    assert manager.is_allowed("k8s_apply", "full") is True
    assert manager.is_allowed("anything_random", "full") is True


async def test_coding_profile_denies_infra(manager: ToolProfileManager):
    assert manager.is_allowed("file_read", "coding") is True
    assert manager.is_allowed("shell_exec", "coding") is True
    assert manager.is_allowed("k8s_list_pods", "coding") is False
    assert manager.is_allowed("proxmox_list_vms", "coding") is False


async def test_readonly_profile(manager: ToolProfileManager):
    assert manager.is_allowed("file_read", "readonly") is True
    assert manager.is_allowed("git_status", "readonly") is True
    assert manager.is_allowed("file_write", "readonly") is False
    assert manager.is_allowed("shell_exec", "readonly") is False
    assert manager.is_allowed("git_commit", "readonly") is False


async def test_minimal_profile(manager: ToolProfileManager):
    assert manager.is_allowed("git_status", "minimal") is True
    assert manager.is_allowed("list_files", "minimal") is True
    assert manager.is_allowed("shell_exec", "minimal") is False
    assert manager.is_allowed("file_read", "minimal") is False


async def test_resolve_groups(manager: ToolProfileManager):
    result = manager.resolve_groups(["group:fs"])
    assert "file_read" in result
    assert "file_write" in result
    assert "list_files" in result

    result_all = manager.resolve_groups(["group:all"])
    assert "*" in result_all


async def test_register_custom_profile(manager: ToolProfileManager):
    manager.register_profile(
        "custom",
        allow=["group:fs"],
        deny=["group:runtime"],
        description="Custom profile",
    )
    assert manager.get_profile("custom") is not None
    assert manager.is_allowed("file_read", "custom") is True
    assert manager.is_allowed("shell_exec", "custom") is False
    # Clean up
    PROFILES.pop("custom", None)


async def test_is_allowed_checks(manager: ToolProfileManager):
    # Unknown profile allows everything
    assert manager.is_allowed("anything", "nonexistent_profile") is True

    profiles = manager.list_profiles()
    assert len(profiles) >= 4
    names = {p["name"] for p in profiles}
    assert "full" in names
    assert "coding" in names
    assert "readonly" in names
    assert "minimal" in names
