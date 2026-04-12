"""Advanced browser action functions for Playwright Page objects.

Provides fine-grained browser interactions: hover, drag-drop, file upload,
option selection, scrolling, keyboard input, cookie management, storage
access, navigation waiting, and PDF export.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


async def hover(page: Any, selector: str, timeout: int = 10000) -> str:
    """Hover the mouse over a page element.

    Args:
        page: Playwright Page object.
        selector: CSS/XPath selector for the target element.
        timeout: Maximum wait time in milliseconds.

    Returns:
        Confirmation message string.
    """
    await page.hover(selector, timeout=timeout)
    return f"Hovered over: {selector}"


async def drag_drop(
    page: Any,
    source: str,
    target: str,
    timeout: int = 10000,
) -> str:
    """Drag an element from source to target.

    Args:
        page: Playwright Page object.
        source: CSS/XPath selector for the element to drag.
        target: CSS/XPath selector for the drop destination.
        timeout: Maximum wait time in milliseconds.

    Returns:
        Confirmation message string.
    """
    await page.drag_and_drop(source, target, timeout=timeout)
    return f"Dragged {source} to {target}"


async def upload_file(
    page: Any,
    selector: str,
    file_paths: list[str],
) -> str:
    """Upload files via a file input element.

    Args:
        page: Playwright Page object.
        selector: CSS selector targeting the file input element.
        file_paths: List of absolute paths to files to upload.

    Returns:
        Confirmation message string, or '[error]' if element not found.
    """
    element = await page.query_selector(selector)
    if element is None:
        return f"[error] File input element not found: {selector}"

    await element.set_input_files(file_paths)
    names = [os.path.basename(p) for p in file_paths]
    return f"Uploaded {len(file_paths)} file(s): {', '.join(names)}"


async def select_option(
    page: Any,
    selector: str,
    value: str = "",
    label: str = "",
    index: int | None = None,
) -> str:
    """Select an option from a <select> element.

    Exactly one of value, label, or index should be provided.

    Args:
        page: Playwright Page object.
        selector: CSS selector for the <select> element.
        value: Option value attribute to select.
        label: Option visible text to select.
        index: Zero-based index of the option to select.

    Returns:
        Confirmation message with selected values.
    """
    if index is not None:
        selected = await page.select_option(selector, index=index)
    elif label:
        selected = await page.select_option(selector, label=label)
    else:
        selected = await page.select_option(selector, value=value)

    return f"Selected: {selected}"


async def scroll(
    page: Any,
    direction: str = "down",
    amount: int = 500,
    selector: str = "",
) -> str:
    """Scroll the page or a specific element.

    Args:
        page: Playwright Page object.
        direction: 'down', 'up', 'right', or 'left'.
        amount: Number of pixels to scroll.
        selector: Optional CSS selector to scroll a specific element.
                  If empty, scrolls the window.

    Returns:
        Confirmation message string.
    """
    sign = -1 if direction in ("up", "left") else 1
    x_delta = sign * amount if direction in ("left", "right") else 0
    y_delta = sign * amount if direction in ("up", "down") else 0

    if selector:
        js = (
            f"document.querySelector('{selector}')"
            f".scrollBy({x_delta}, {y_delta})"
        )
    else:
        js = f"window.scrollBy({x_delta}, {y_delta})"

    await page.evaluate(js)
    return f"Scrolled {direction} by {amount}px"


async def press_key(
    page: Any,
    key: str,
    modifiers: str = "",
) -> str:
    """Press a keyboard key, optionally with modifier keys.

    Args:
        page: Playwright Page object.
        key: Key name as recognised by Playwright (e.g. 'Enter', 'Tab', 'a').
        modifiers: '+'-separated modifiers to hold (e.g. 'Control+Shift').
                   If provided, combined with key: 'Control+Shift+a'.

    Returns:
        Confirmation message with the key combo pressed.
    """
    combo = f"{modifiers}+{key}" if modifiers else key
    await page.keyboard.press(combo)
    return f"Pressed: {combo}"


async def get_cookies(page: Any, urls: list[str] | None = None) -> list[dict]:
    """Retrieve cookies from the browser context.

    Args:
        page: Playwright Page object.
        urls: Optional list of URLs to filter cookies by.

    Returns:
        List of cookie dicts with name, value, domain, path, etc.
    """
    if urls:
        cookies = await page.context.cookies(urls)
    else:
        cookies = await page.context.cookies()
    return cookies


async def set_cookie(page: Any, cookie: dict) -> str:
    """Add a cookie to the browser context.

    Args:
        page: Playwright Page object.
        cookie: Cookie dict with at minimum 'name', 'value', and 'url' or
                'domain'+'path'.

    Returns:
        Confirmation message with the cookie name.
    """
    await page.context.add_cookies([cookie])
    return f"Cookie set: {cookie.get('name', '<unnamed>')}"


async def get_storage(page: Any, storage_type: str = "local") -> dict:
    """Read all entries from localStorage or sessionStorage.

    Args:
        page: Playwright Page object.
        storage_type: 'local' for localStorage, 'session' for sessionStorage.

    Returns:
        Dict mapping storage keys to their string values.
    """
    store = "localStorage" if storage_type == "local" else "sessionStorage"
    result = await page.evaluate(
        f"Object.fromEntries(Object.entries({store}))"
    )
    return result if isinstance(result, dict) else {}


async def wait_for_navigation(
    page: Any,
    url_pattern: str = "",
    timeout: int = 10000,
) -> str:
    """Wait for the page to finish navigating.

    If url_pattern is given, waits until the URL matches it.
    Otherwise waits for 'load' state.

    Args:
        page: Playwright Page object.
        url_pattern: Optional glob/regex pattern the URL must match.
        timeout: Maximum wait time in milliseconds.

    Returns:
        Confirmation message.
    """
    if url_pattern:
        await page.wait_for_url(url_pattern, timeout=timeout)
        return f"Navigation complete — URL matches: {url_pattern}"
    else:
        await page.wait_for_load_state("load", timeout=timeout)
        return "Navigation complete — page loaded"


async def export_pdf(page: Any, path: str = "") -> str:
    """Export the current page as a PDF.

    Args:
        page: Playwright Page object (must be Chromium).
        path: Optional filesystem path to save the PDF.  If empty the PDF
              bytes are returned as a base64-encoded string embedded in the
              result message.

    Returns:
        Confirmation message.  If no path given, includes 'PDF (base64): …'.
    """
    pdf_bytes: bytes = await page.pdf()

    if path:
        with open(path, "wb") as fh:
            fh.write(pdf_bytes)
        return f"PDF exported to: {path}"

    encoded = base64.b64encode(pdf_bytes).decode("ascii")
    return f"PDF (base64): {encoded[:80]}…" if len(encoded) > 80 else f"PDF (base64): {encoded}"
