"""Computer use (GUI automation) foundation. Provides screenshot and basic input tools.
Requires platform-specific backends (not included). Falls back to description-only mode."""
from __future__ import annotations
import base64
import logging
from dataclasses import dataclass
from breadmind.tools.registry import tool

logger = logging.getLogger(__name__)

@dataclass
class ScreenRegion:
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

@tool("Take a screenshot of the screen or a region", read_only=True)
async def screenshot(region: str = "") -> str:
    """Take screenshot. region format: 'x,y,width,height' or empty for full screen."""
    try:
        import pyautogui
        if region:
            parts = [int(p) for p in region.split(",")]
            img = pyautogui.screenshot(region=tuple(parts))
        else:
            img = pyautogui.screenshot()

        import io
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f'{{"type":"screenshot","format":"png","width":{img.width},"height":{img.height},"base64":"{b64[:50]}..."}}'
    except ImportError:
        return "Screenshot requires pyautogui. Install: pip install pyautogui"
    except Exception as e:
        return f"Screenshot failed: {e}"

@tool("Click at a screen position", read_only=False)
async def mouse_click(x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    try:
        import pyautogui
        pyautogui.click(x, y, button=button, clicks=clicks)
        return f"Clicked at ({x}, {y}) with {button} button"
    except ImportError:
        return "Mouse control requires pyautogui"
    except Exception as e:
        return f"Click failed: {e}"

@tool("Type text using keyboard", read_only=False)
async def keyboard_type(text: str, interval: float = 0.02) -> str:
    try:
        import pyautogui
        pyautogui.typewrite(text, interval=interval)
        return f"Typed {len(text)} characters"
    except ImportError:
        return "Keyboard control requires pyautogui"
    except Exception as e:
        return f"Type failed: {e}"

@tool("Press a keyboard key or hotkey", read_only=False)
async def keyboard_press(key: str) -> str:
    """Press a key. For hotkeys use '+': 'ctrl+c', 'alt+tab'."""
    try:
        import pyautogui
        if "+" in key:
            keys = key.split("+")
            pyautogui.hotkey(*keys)
        else:
            pyautogui.press(key)
        return f"Pressed: {key}"
    except ImportError:
        return "Keyboard control requires pyautogui"
    except Exception as e:
        return f"Key press failed: {e}"
