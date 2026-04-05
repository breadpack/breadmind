"""Tests for computer use (GUI automation) foundation tools."""
from __future__ import annotations
import sys
from unittest.mock import patch

from breadmind.tools.computer_use import (
    screenshot,
    mouse_click,
    keyboard_type,
    keyboard_press,
)


async def test_screenshot_no_pyautogui():
    with patch.dict(sys.modules, {"pyautogui": None}):
        # Force re-import failure
        result = await screenshot()
    assert "pyautogui" in result.lower() or "screenshot" in result.lower()


async def test_mouse_click_no_pyautogui():
    with patch.dict(sys.modules, {"pyautogui": None}):
        result = await mouse_click(100, 200)
    assert "pyautogui" in result.lower() or "mouse" in result.lower()


async def test_keyboard_type_no_pyautogui():
    with patch.dict(sys.modules, {"pyautogui": None}):
        result = await keyboard_type("hello")
    assert "pyautogui" in result.lower() or "keyboard" in result.lower()


async def test_keyboard_press_no_pyautogui():
    with patch.dict(sys.modules, {"pyautogui": None}):
        result = await keyboard_press("enter")
    assert "pyautogui" in result.lower() or "keyboard" in result.lower()
