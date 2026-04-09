"""Windows keyboard & mouse input helpers using ctypes/user32.dll.

Extracted from windows_adapter.py to keep file sizes under 500 lines.
Uses only stdlib ctypes -- no external dependencies.
"""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes
import logging

logger = logging.getLogger(__name__)

# --- SendInput constants ---

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
WHEEL_DELTA = 120

# --- Virtual key code mapping ---

VK_MAP: dict[str, int] = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "escape": 0x1B, "esc": 0x1B,
    "space": 0x20, "backspace": 0x08, "delete": 0x2E, "insert": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "ctrl": 0xA2, "lctrl": 0xA2, "rctrl": 0xA3,
    "alt": 0xA4, "lalt": 0xA4, "ralt": 0xA5, "menu": 0xA4,
    "shift": 0xA0, "lshift": 0xA0, "rshift": 0xA1,
    "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C,
    "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91,
    "printscreen": 0x2C, "pause": 0x13,
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
    **{chr(c): c for c in range(0x30, 0x3A)},  # 0-9
    **{chr(c).lower(): c for c in range(0x41, 0x5B)},  # a-z
}

# --- ctypes structures for SendInput ---


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", INPUT_UNION)]


# --- Helper functions ---


async def send_unicode_char(char: str) -> None:
    """Type a single character via SendInput with KEYEVENTF_UNICODE."""
    user32 = ctypes.windll.user32
    inputs = (INPUT * 2)()
    # Key down
    inputs[0].type = INPUT_KEYBOARD
    inputs[0].union.ki.wVk = 0
    inputs[0].union.ki.wScan = ord(char)
    inputs[0].union.ki.dwFlags = KEYEVENTF_UNICODE
    # Key up
    inputs[1].type = INPUT_KEYBOARD
    inputs[1].union.ki.wVk = 0
    inputs[1].union.ki.wScan = ord(char)
    inputs[1].union.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    await asyncio.get_event_loop().run_in_executor(
        None, lambda: user32.SendInput(2, inputs, ctypes.sizeof(INPUT))
    )


async def send_key_combo(key: str, modifiers: list[str] | None = None) -> None:
    """Press a key combination via SendInput."""
    user32 = ctypes.windll.user32
    modifiers = modifiers or []
    vk_main = VK_MAP.get(key.lower())
    if vk_main is None:
        raise ValueError(f"Unknown key: {key}")
    mod_vks: list[int] = []
    for mod in modifiers:
        vk = VK_MAP.get(mod.lower())
        if vk is None:
            raise ValueError(f"Unknown modifier: {mod}")
        mod_vks.append(vk)

    total = len(mod_vks) * 2 + 2
    inputs = (INPUT * total)()
    idx = 0
    # Press modifiers
    for vk in mod_vks:
        inputs[idx].type = INPUT_KEYBOARD
        inputs[idx].union.ki.wVk = vk
        idx += 1
    # Press main key
    inputs[idx].type = INPUT_KEYBOARD
    inputs[idx].union.ki.wVk = vk_main
    idx += 1
    # Release main key
    inputs[idx].type = INPUT_KEYBOARD
    inputs[idx].union.ki.wVk = vk_main
    inputs[idx].union.ki.dwFlags = KEYEVENTF_KEYUP
    idx += 1
    # Release modifiers (reverse order)
    for vk in reversed(mod_vks):
        inputs[idx].type = INPUT_KEYBOARD
        inputs[idx].union.ki.wVk = vk
        inputs[idx].union.ki.dwFlags = KEYEVENTF_KEYUP
        idx += 1

    await asyncio.get_event_loop().run_in_executor(
        None, lambda: user32.SendInput(total, inputs, ctypes.sizeof(INPUT))
    )


async def send_mouse_click(
    button: str = "left", clicks: int = 1
) -> None:
    """Send mouse click(s) at the current cursor position."""
    user32 = ctypes.windll.user32
    button_map = {
        "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    }
    down_flag, up_flag = button_map.get(button, button_map["left"])
    for _ in range(clicks):
        inputs = (INPUT * 2)()
        inputs[0].type = INPUT_MOUSE
        inputs[0].union.mi.dwFlags = down_flag
        inputs[1].type = INPUT_MOUSE
        inputs[1].union.mi.dwFlags = up_flag
        await asyncio.get_event_loop().run_in_executor(
            None, lambda inp=inputs: user32.SendInput(2, inp, ctypes.sizeof(INPUT))
        )


async def send_mouse_scroll(direction: str = "down", amount: int = 3) -> None:
    """Send mouse scroll at the current cursor position."""
    delta = -WHEEL_DELTA * amount if direction == "down" else WHEEL_DELTA * amount
    inputs = (INPUT * 1)()
    inputs[0].type = INPUT_MOUSE
    inputs[0].union.mi.dwFlags = MOUSEEVENTF_WHEEL
    inputs[0].union.mi.mouseData = delta & 0xFFFFFFFF
    await asyncio.get_event_loop().run_in_executor(
        None, lambda: ctypes.windll.user32.SendInput(1, inputs, ctypes.sizeof(INPUT))
    )
