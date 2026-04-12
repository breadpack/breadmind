"""Browser action dispatcher for BrowserEngine.

Handles the do_action method logic, dispatching to the appropriate
browser_actions module functions based on the action type.
"""
from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING

from breadmind.tools.browser_actions import (
    hover, drag_drop, upload_file, select_option, scroll,
    press_key, get_cookies, set_cookie, get_storage,
    export_pdf,
)

if TYPE_CHECKING:
    from breadmind.tools.browser_session import BrowserSession

logger = logging.getLogger(__name__)

_AVAILABLE_ACTIONS = (
    "click, fill, hover, drag_drop, upload_file, select_option, scroll, "
    "press_key, get_cookies, set_cookie, get_storage, wait, back, pdf, "
    "evaluate, tabs, new_tab, switch_tab"
)


async def dispatch_action(
    sess: "BrowserSession",
    session_mgr: Any,
    action: str,
    default_timeout: int,
    **kwargs: Any,
) -> str:
    """Dispatch a browser action to the correct handler.

    Args:
        sess: The resolved BrowserSession to act on.
        session_mgr: SessionManager instance (needed for new_tab).
        action: The action name string.
        default_timeout: Fallback timeout in milliseconds.
        **kwargs: Action-specific parameters.

    Returns:
        Result string.
    """
    page = sess.page
    timeout = kwargs.get("timeout", default_timeout)

    if action == "click":
        selector = kwargs.get("selector", "")
        text = kwargs.get("text", "")
        if selector:
            await page.click(selector, timeout=timeout)
            result = f"Clicked: {selector}"
        elif text:
            await page.get_by_text(text, exact=False).first.click(timeout=timeout)
            result = f"Clicked text: {text}"
        else:
            return "[error] selector or text required for click"
        await page.wait_for_load_state("domcontentloaded", timeout=timeout)
        result += f"\nURL: {page.url}"

    elif action == "fill":
        selector = kwargs.get("selector", "")
        value = kwargs.get("value", "")
        if not selector:
            return "[error] selector required for fill"
        await page.fill(selector, value, timeout=timeout)
        result = f"Filled '{selector}' with value (length={len(value)})"

    elif action == "hover":
        selector = kwargs.get("selector", "")
        result = await hover(page, selector, timeout=timeout)

    elif action == "drag_drop":
        source = kwargs.get("source", "")
        target = kwargs.get("target", "")
        result = await drag_drop(page, source, target, timeout=timeout)

    elif action == "upload_file":
        selector = kwargs.get("selector", "")
        value = kwargs.get("value", "")
        file_paths = [p.strip() for p in value.split(",") if p.strip()]
        result = await upload_file(page, selector, file_paths)

    elif action == "select_option":
        selector = kwargs.get("selector", "")
        value = kwargs.get("value", "")
        index_raw = kwargs.get("index")
        index = int(index_raw) if index_raw is not None else None
        result = await select_option(page, selector, value=value, index=index)

    elif action == "scroll":
        direction = kwargs.get("direction", "down")
        amount = int(kwargs.get("amount", 500))
        selector = kwargs.get("selector", "")
        result = await scroll(page, direction=direction, amount=amount, selector=selector)

    elif action == "press_key":
        key = kwargs.get("key", "")
        result = await press_key(page, key)

    elif action == "get_cookies":
        cookies = await get_cookies(page)
        result = json.dumps(cookies, ensure_ascii=False, default=str)

    elif action == "set_cookie":
        value = kwargs.get("value", "")
        try:
            cookie = json.loads(value) if value else {}
        except json.JSONDecodeError:
            return "[error] value must be a JSON-encoded cookie dict"
        result = await set_cookie(page, cookie)

    elif action == "get_storage":
        storage_type = kwargs.get("value", "local")
        data = await get_storage(page, storage_type=storage_type)
        result = json.dumps(data, ensure_ascii=False, default=str)

    elif action == "wait":
        selector = kwargs.get("selector", "")
        if not selector:
            return "[error] selector required for wait"
        await page.wait_for_selector(selector, timeout=timeout)
        result = f"Element found: {selector}"

    elif action == "back":
        await page.go_back(timeout=timeout)
        title = await page.title()
        result = f"Navigated back to: {page.url}\nTitle: {title}"

    elif action == "pdf":
        path = kwargs.get("value", "")
        result = await export_pdf(page, path=path)

    elif action == "evaluate":
        javascript = kwargs.get("javascript", "")
        if not javascript:
            return "[error] javascript required for evaluate"
        js_result = await page.evaluate(javascript)
        result = json.dumps(js_result, ensure_ascii=False, default=str)

    elif action == "tabs":
        pages = page.context.pages
        lines = [f"Open tabs ({len(pages)}):"]
        for i, p in enumerate(pages):
            marker = " (active)" if p == page else ""
            lines.append(f"  [{i}] {p.url}{marker}")
        result = "\n".join(lines)

    elif action == "new_tab":
        url = kwargs.get("url", "")
        new_page = await session_mgr.new_tab(sess.id, url=url, timeout=timeout)
        sess.page = new_page
        title = await new_page.title()
        result = f"New tab opened: {new_page.url}\nTitle: {title}"

    elif action == "switch_tab":
        index = int(kwargs.get("index", 0))
        pages = page.context.pages
        if 0 <= index < len(pages):
            sess.page = pages[index]
            await sess.page.bring_to_front()
            title = await sess.page.title()
            result = f"Switched to tab [{index}]: {sess.page.url}\nTitle: {title}"
        else:
            return f"[error] Invalid tab index: {index}. Open tabs: {len(pages)}"

    else:
        return f"[error] Unknown action: {action}. Available: {_AVAILABLE_ACTIONS}"

    return result
