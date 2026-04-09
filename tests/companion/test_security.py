"""Tests for PermissionManager and path sandboxing."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from breadmind.companion.security import PermissionManager


def test_default_permissions():
    pm = PermissionManager()
    assert pm.is_allowed("companion_system_info") is True
    assert pm.is_allowed("companion_screenshot") is True
    assert pm.is_allowed("companion_clipboard_read") is False
    assert pm.is_allowed("companion_power") is False


def test_custom_capabilities():
    pm = PermissionManager(capabilities={
        "companion_clipboard_read": True,
        "companion_power": True,
    })
    assert pm.is_allowed("companion_clipboard_read") is True
    assert pm.is_allowed("companion_power") is True


def test_unknown_tool_denied():
    pm = PermissionManager()
    assert pm.is_allowed("nonexistent_tool") is False


def test_path_no_restrictions():
    pm = PermissionManager()
    assert pm.check_path("/tmp/somefile.txt") is True


def test_path_allowed_paths():
    pm = PermissionManager(allowed_paths=["/tmp/allowed"])
    assert pm.check_path("/tmp/allowed/file.txt") is True
    assert pm.check_path("/etc/passwd") is False


def test_path_denied_paths():
    pm = PermissionManager(denied_paths=["/etc"])
    assert pm.check_path("/etc/passwd") is False
    assert pm.check_path("/tmp/safe.txt") is True


def test_path_denied_takes_priority():
    pm = PermissionManager(
        allowed_paths=["/home"],
        denied_paths=["/home/secret"],
    )
    assert pm.check_path("/home/user/file.txt") is True
    assert pm.check_path("/home/secret/key.pem") is False


def test_path_traversal_blocked():
    with tempfile.TemporaryDirectory() as tmpdir:
        allowed = Path(tmpdir) / "allowed"
        allowed.mkdir()
        pm = PermissionManager(allowed_paths=[str(allowed)])
        # Traversal should resolve and fail
        assert pm.check_path(str(allowed / ".." / "etc" / "passwd")) is False


def test_requires_confirmation():
    pm = PermissionManager()
    assert pm.requires_confirmation("companion_power") is True
    assert pm.requires_confirmation("companion_process_kill") is True
    assert pm.requires_confirmation("companion_system_info") is False


def test_requires_confirmation_new_tools():
    pm = PermissionManager()
    assert pm.requires_confirmation("companion_window_close") is True
    assert pm.requires_confirmation("companion_type_text") is True
    assert pm.requires_confirmation("companion_press_key") is True
    assert pm.requires_confirmation("companion_mouse_click") is True


def test_input_control_default_disabled():
    pm = PermissionManager()
    assert pm.is_allowed("companion_type_text") is False
    assert pm.is_allowed("companion_press_key") is False
    assert pm.is_allowed("companion_mouse_move") is False
    assert pm.is_allowed("companion_mouse_click") is False
    assert pm.is_allowed("companion_mouse_scroll") is False


def test_window_mgmt_default_enabled():
    pm = PermissionManager()
    assert pm.is_allowed("companion_window_list") is True
    assert pm.is_allowed("companion_window_focus") is True
    assert pm.is_allowed("companion_window_move") is True
    assert pm.is_allowed("companion_window_minimize") is True
    assert pm.is_allowed("companion_window_maximize") is True
    assert pm.is_allowed("companion_window_screenshot") is True
    # window_close is excluded from default window_mgmt enable
    assert pm.is_allowed("companion_window_close") is False


def test_input_control_capability_enables_all():
    pm = PermissionManager(capabilities={"input_control": True})
    assert pm.is_allowed("companion_type_text") is True
    assert pm.is_allowed("companion_press_key") is True
    assert pm.is_allowed("companion_mouse_move") is True
    assert pm.is_allowed("companion_mouse_click") is True
    assert pm.is_allowed("companion_mouse_scroll") is True


def test_window_mgmt_capability_disables_all():
    pm = PermissionManager(capabilities={"window_mgmt": False})
    assert pm.is_allowed("companion_window_list") is False
    assert pm.is_allowed("companion_window_focus") is False
    assert pm.is_allowed("companion_window_move") is False
