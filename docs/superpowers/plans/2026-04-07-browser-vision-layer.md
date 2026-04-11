# Browser AI Vision Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable BreadMind's browser to "see" web pages by extracting screenshots into LLM-compatible Attachment objects, analyzing pages with LLM Vision, and providing smart element interaction via natural language descriptions.

**Architecture:** Three layers: ScreenshotProcessor (tag extraction + Attachment conversion), PageAnalyzer (screenshot + a11y tree → LLM Vision analysis), VisionBrowser (high-level tools: analyze, find_element, smart_click, smart_fill). ToolExecutor gets a post-processing hook to auto-convert browser screenshots into images the LLM can see.

**Tech Stack:** Python 3.12+, regex, existing LLM providers (Claude/Gemini with vision), existing BrowserEngine, pytest + pytest-asyncio

---

### Task 1: ScreenshotProcessor — extract and convert screenshot tags

**Files:**
- Create: `src/breadmind/tools/browser_screenshot.py`
- Create: `tests/tools/test_browser_screenshot.py`

- [ ] **Step 1: Write tests**

Create `tests/tools/test_browser_screenshot.py`:

```python
"""Tests for screenshot tag extraction and Attachment conversion."""
from __future__ import annotations

import base64
import pytest


def test_extract_single_screenshot():
    from breadmind.tools.browser_screenshot import process_tool_result
    img_data = base64.b64encode(b"fake-png-data").decode()
    content = f"Screenshot captured\nURL: https://example.com\n[screenshot_base64]{img_data}[/screenshot_base64]"
    cleaned, attachments = process_tool_result(content)
    assert "[screenshot_base64]" not in cleaned
    assert len(attachments) == 1
    assert attachments[0].type == "image"
    assert attachments[0].data == img_data
    assert attachments[0].media_type == "image/png"


def test_extract_multiple_screenshots():
    from breadmind.tools.browser_screenshot import process_tool_result
    img1 = base64.b64encode(b"img1").decode()
    img2 = base64.b64encode(b"img2").decode()
    content = f"[screenshot_base64]{img1}[/screenshot_base64] middle [screenshot_base64]{img2}[/screenshot_base64]"
    cleaned, attachments = process_tool_result(content)
    assert len(attachments) == 2
    assert "[screenshot_base64]" not in cleaned


def test_no_screenshots():
    from breadmind.tools.browser_screenshot import process_tool_result
    content = "Navigated to https://example.com\nTitle: Example"
    cleaned, attachments = process_tool_result(content)
    assert cleaned == content
    assert len(attachments) == 0


def test_pdf_tag_extraction():
    from breadmind.tools.browser_screenshot import process_tool_result
    pdf_data = base64.b64encode(b"%PDF-fake").decode()
    content = f"PDF exported\n[pdf_base64]{pdf_data}[/pdf_base64]"
    cleaned, attachments = process_tool_result(content)
    assert "[pdf_base64]" not in cleaned
    assert len(attachments) == 1
    assert attachments[0].media_type == "application/pdf"


def test_cleaned_text_preserves_metadata():
    from breadmind.tools.browser_screenshot import process_tool_result
    img_data = base64.b64encode(b"png").decode()
    content = f"Screenshot (100 bytes)\nURL: https://x.com\nTitle: X\n[screenshot_base64]{img_data}[/screenshot_base64]"
    cleaned, _ = process_tool_result(content)
    assert "URL: https://x.com" in cleaned
    assert "Title: X" in cleaned


def test_is_browser_tool():
    from breadmind.tools.browser_screenshot import is_browser_tool
    assert is_browser_tool("browser_screenshot") is True
    assert is_browser_tool("browser_navigate") is True
    assert is_browser_tool("browser_action") is True
    assert is_browser_tool("shell_exec") is False
    assert is_browser_tool("browser") is True
```

- [ ] **Step 2: Run tests — should fail**

Run: `python -m pytest tests/tools/test_browser_screenshot.py -v`

- [ ] **Step 3: Implement browser_screenshot.py**

Create `src/breadmind/tools/browser_screenshot.py`:

```python
"""Screenshot extraction from tool results — converts base64 tags to Attachments."""
from __future__ import annotations

import re
from breadmind.llm.base import Attachment

_SCREENSHOT_RE = re.compile(
    r"\[screenshot_base64\](.*?)\[/screenshot_base64\]", re.DOTALL
)
_PDF_RE = re.compile(
    r"\[pdf_base64\](.*?)\[/pdf_base64\]", re.DOTALL
)

_BROWSER_TOOL_PREFIXES = ("browser_", "browser")


def is_browser_tool(tool_name: str) -> bool:
    """Check if a tool name belongs to the browser engine."""
    return tool_name.startswith(_BROWSER_TOOL_PREFIXES)


def process_tool_result(content: str) -> tuple[str, list[Attachment]]:
    """Extract screenshot/PDF tags from tool result, return cleaned text + attachments."""
    attachments: list[Attachment] = []

    # Extract screenshots
    for match in _SCREENSHOT_RE.finditer(content):
        data = match.group(1).strip()
        attachments.append(Attachment(
            type="image",
            data=data,
            media_type="image/png",
        ))

    # Extract PDFs
    for match in _PDF_RE.finditer(content):
        data = match.group(1).strip()
        attachments.append(Attachment(
            type="file",
            data=data,
            media_type="application/pdf",
        ))

    # Remove tags from text content
    cleaned = _SCREENSHOT_RE.sub("", content)
    cleaned = _PDF_RE.sub("", cleaned)
    cleaned = cleaned.strip()

    return cleaned, attachments
```

- [ ] **Step 4: Run tests — all 6 should pass**

Run: `python -m pytest tests/tools/test_browser_screenshot.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/browser_screenshot.py tests/tools/test_browser_screenshot.py
git commit -m "feat(browser): add screenshot tag extraction and Attachment conversion"
```

---

### Task 2: Hook ScreenshotProcessor into ToolExecutor

**Files:**
- Modify: `src/breadmind/core/tool_executor.py` (lines 212-216)

- [ ] **Step 1: Add screenshot processing after tool message creation**

In `tool_executor.py`, find lines 212-216:

```python
            tool_msg = LLMMessage(
                role="tool", content=output,
                tool_call_id=tc.id, name=tc.name,
            )
            messages.append(tool_msg)
```

Replace with:

```python
            tool_msg = LLMMessage(
                role="tool", content=output,
                tool_call_id=tc.id, name=tc.name,
            )
            # Extract screenshots/PDFs from browser tool results into Attachments
            if is_browser_tool(tc.name):
                cleaned, attachments = process_browser_result(tool_msg.content or "")
                if attachments:
                    tool_msg.content = cleaned
                    tool_msg.attachments = attachments
            messages.append(tool_msg)
```

Also add the import at the top of the file (in the imports section):

```python
from breadmind.tools.browser_screenshot import (
    is_browser_tool,
    process_tool_result as process_browser_result,
)
```

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/core/tool_executor.py
git commit -m "feat(browser): hook screenshot extraction into ToolExecutor pipeline"
```

---

### Task 3: PageAnalyzer — vision-based page understanding

**Files:**
- Create: `src/breadmind/tools/browser_page_analyzer.py`
- Create: `tests/tools/test_browser_page_analyzer.py`

- [ ] **Step 1: Write tests**

Create `tests/tools/test_browser_page_analyzer.py`:

```python
"""Tests for PageAnalyzer — LLM Vision page analysis."""
from __future__ import annotations

import base64
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from breadmind.llm.base import LLMResponse, TokenUsage


@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=LLMResponse(
        content="This is a login page with email and password fields and a Sign In button.",
        tool_calls=[],
        usage=TokenUsage(input_tokens=500, output_tokens=50),
        stop_reason="end_turn",
    ))
    return provider


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.screenshot = AsyncMock(return_value=(
        "Screenshot (1024 bytes)\nURL: https://example.com\nTitle: Login\n"
        f"[screenshot_base64]{base64.b64encode(b'fake-png').decode()}[/screenshot_base64]"
    ))
    engine.get_a11y_tree = AsyncMock(return_value=(
        'Accessibility Tree (~20 tokens):\n'
        '[textbox "Email" value=""]\n'
        '[textbox "Password" value="" type=password]\n'
        '[button "Sign In"]'
    ))
    return engine


async def test_analyze_page(mock_provider, mock_engine):
    from breadmind.tools.browser_page_analyzer import PageAnalyzer
    analyzer = PageAnalyzer(mock_provider, mock_engine)
    result = await analyzer.analyze_page(session="s1", question="What is on this page?")
    assert "login" in result.lower()
    mock_provider.chat.assert_called_once()
    call_args = mock_provider.chat.call_args
    messages = call_args[0][0]
    # Should have image attachment
    has_image = any(a.type == "image" for m in messages for a in m.attachments)
    assert has_image


async def test_find_element(mock_provider, mock_engine):
    from breadmind.tools.browser_page_analyzer import PageAnalyzer
    mock_provider.chat = AsyncMock(return_value=LLMResponse(
        content='[textbox "Email"]',
        tool_calls=[],
        usage=TokenUsage(input_tokens=400, output_tokens=20),
        stop_reason="end_turn",
    ))
    analyzer = PageAnalyzer(mock_provider, mock_engine)
    result = await analyzer.find_element(session="s1", description="the email input field")
    assert "Email" in result


async def test_analyze_page_no_question(mock_provider, mock_engine):
    from breadmind.tools.browser_page_analyzer import PageAnalyzer
    analyzer = PageAnalyzer(mock_provider, mock_engine)
    result = await analyzer.analyze_page(session="s1")
    assert len(result) > 0


async def test_build_vision_prompt():
    from breadmind.tools.browser_page_analyzer import PageAnalyzer
    prompt = PageAnalyzer.build_analysis_prompt(
        a11y_tree='[button "OK"]',
        question="What button is on the page?",
        network_summary=None,
    )
    assert "button" in prompt.lower()
    assert "What button" in prompt
```

- [ ] **Step 2: Run tests — should fail**

Run: `python -m pytest tests/tools/test_browser_page_analyzer.py -v`

- [ ] **Step 3: Implement browser_page_analyzer.py**

Create `src/breadmind/tools/browser_page_analyzer.py`:

```python
"""Page analysis using LLM Vision — combines screenshots with accessibility tree."""
from __future__ import annotations

import base64
import logging
import re
from typing import Any

from breadmind.llm.base import Attachment, LLMMessage

logger = logging.getLogger(__name__)

_SCREENSHOT_RE = re.compile(
    r"\[screenshot_base64\](.*?)\[/screenshot_base64\]", re.DOTALL
)


class PageAnalyzer:
    """Analyze web pages by sending screenshot + a11y tree to LLM Vision."""

    def __init__(self, llm_provider: Any, browser_engine: Any) -> None:
        self._llm = llm_provider
        self._engine = browser_engine

    async def analyze_page(
        self,
        session: str = "",
        question: str = "",
        include_network: bool = False,
    ) -> str:
        """Capture screenshot + a11y tree, send to LLM Vision, return analysis."""
        # Capture screenshot
        screenshot_result = await self._engine.screenshot(session=session)
        screenshot_data = self._extract_screenshot(screenshot_result)

        # Extract a11y tree (interactive only for token efficiency)
        a11y_result = await self._engine.get_a11y_tree(
            session=session, interactive_only=True, max_depth=8,
        )

        # Build prompt
        prompt_text = self.build_analysis_prompt(
            a11y_tree=a11y_result,
            question=question,
            network_summary=None,
        )

        # Build message with image attachment
        attachments = []
        if screenshot_data:
            attachments.append(Attachment(
                type="image",
                data=screenshot_data,
                media_type="image/png",
            ))

        messages = [
            LLMMessage(role="user", content=prompt_text, attachments=attachments),
        ]

        response = await self._llm.chat(messages)
        return response.content or ""

    async def find_element(
        self,
        session: str = "",
        description: str = "",
    ) -> str:
        """Find element matching natural language description using vision."""
        screenshot_result = await self._engine.screenshot(session=session)
        screenshot_data = self._extract_screenshot(screenshot_result)

        a11y_result = await self._engine.get_a11y_tree(
            session=session, interactive_only=True, max_depth=8,
        )

        prompt_text = self.build_find_element_prompt(
            a11y_tree=a11y_result,
            description=description,
        )

        attachments = []
        if screenshot_data:
            attachments.append(Attachment(
                type="image",
                data=screenshot_data,
                media_type="image/png",
            ))

        messages = [
            LLMMessage(role="user", content=prompt_text, attachments=attachments),
        ]

        response = await self._llm.chat(messages)
        return response.content or ""

    @staticmethod
    def _extract_screenshot(result: str) -> str | None:
        """Extract base64 screenshot data from tool result string."""
        match = _SCREENSHOT_RE.search(result)
        return match.group(1).strip() if match else None

    @staticmethod
    def build_analysis_prompt(
        a11y_tree: str,
        question: str = "",
        network_summary: str | None = None,
    ) -> str:
        """Build the prompt for page analysis."""
        parts = [
            "Analyze this web page. I'm providing a screenshot and the page's accessibility tree.",
            "",
            "## Accessibility Tree (interactive elements)",
            a11y_tree,
        ]
        if network_summary:
            parts.extend(["", "## Network Activity", network_summary])
        if question:
            parts.extend(["", f"## Question", question])
        else:
            parts.extend([
                "", "## Task",
                "Describe what you see: page purpose, key interactive elements, "
                "current state (logged in/out, form values, errors), and any notable content.",
            ])
        return "\n".join(parts)

    @staticmethod
    def build_find_element_prompt(a11y_tree: str, description: str) -> str:
        """Build prompt for element identification."""
        return (
            f"I need to find a specific element on this web page.\n\n"
            f"## Element Description\n{description}\n\n"
            f"## Accessibility Tree\n{a11y_tree}\n\n"
            f"## Task\n"
            f"Identify the element from the accessibility tree that best matches "
            f"the description. Return ONLY the matching accessibility tree entry "
            f"(e.g., [button \"Sign In\"] or [textbox \"Email\"]). "
            f"If there's a CSS selector that would work, include it as well."
        )
```

- [ ] **Step 4: Run tests — all 4 should pass**

Run: `python -m pytest tests/tools/test_browser_page_analyzer.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/browser_page_analyzer.py tests/tools/test_browser_page_analyzer.py
git commit -m "feat(browser): add PageAnalyzer for LLM Vision page understanding"
```

---

### Task 4: VisionBrowser — high-level vision tools

**Files:**
- Create: `src/breadmind/tools/browser_vision.py`
- Create: `tests/tools/test_browser_vision.py`

- [ ] **Step 1: Write tests**

Create `tests/tools/test_browser_vision.py`:

```python
"""Tests for VisionBrowser high-level vision tools."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_analyzer():
    analyzer = AsyncMock()
    analyzer.analyze_page = AsyncMock(return_value="Login page with email and password fields")
    analyzer.find_element = AsyncMock(return_value='[textbox "Email"]')
    return analyzer


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.do_action = AsyncMock(return_value="Clicked: [textbox \"Email\"]")
    engine.navigate = AsyncMock(return_value="Navigated to: https://example.com")
    return engine


@pytest.fixture
def vision(mock_analyzer, mock_engine):
    from breadmind.tools.browser_vision import VisionBrowser
    return VisionBrowser(mock_analyzer, mock_engine)


async def test_analyze(vision):
    result = await vision.analyze(session="s1", question="What page is this?")
    assert "Login" in result


async def test_find_element(vision):
    result = await vision.find_element(session="s1", description="email input")
    assert "Email" in result


async def test_smart_click(vision, mock_engine):
    result = await vision.smart_click(session="s1", description="the sign in button")
    mock_engine.do_action.assert_called_once()
    assert len(result) > 0


async def test_smart_fill(vision, mock_engine):
    result = await vision.smart_fill(session="s1", description="email field", value="test@test.com")
    mock_engine.do_action.assert_called_once()
    assert len(result) > 0


async def test_get_tool_functions(vision):
    tools = vision.get_tool_functions()
    names = [f.__name__ for f in tools]
    assert "browser_analyze" in names
    assert "browser_find_element" in names
    assert "browser_smart_click" in names
    assert "browser_smart_fill" in names
    assert len(tools) == 4
```

- [ ] **Step 2: Run tests — should fail**

Run: `python -m pytest tests/tools/test_browser_vision.py -v`

- [ ] **Step 3: Implement browser_vision.py**

Create `src/breadmind/tools/browser_vision.py`:

```python
"""High-level vision-based browser tools — natural language element interaction."""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

from breadmind.tools.registry import tool

logger = logging.getLogger(__name__)

# Parse a11y role and name from LLM response like: [button "Sign In"]
_A11Y_ELEMENT_RE = re.compile(r'\[(\w+)\s+"([^"]+)"')


class VisionBrowser:
    """High-level browser tools that use LLM Vision for element identification."""

    def __init__(self, page_analyzer: Any, browser_engine: Any) -> None:
        self._analyzer = page_analyzer
        self._engine = browser_engine

    async def analyze(self, session: str = "", question: str = "") -> str:
        """Analyze current page using LLM Vision."""
        return await self._analyzer.analyze_page(session=session, question=question)

    async def find_element(self, session: str = "", description: str = "") -> str:
        """Find element by natural language description."""
        return await self._analyzer.find_element(session=session, description=description)

    async def smart_click(self, session: str = "", description: str = "") -> str:
        """Find element by description and click it."""
        element_info = await self._analyzer.find_element(
            session=session, description=description,
        )
        selector = self._extract_selector(element_info)
        if not selector:
            return f"[error] Could not identify element for: {description}\nLLM response: {element_info}"

        click_result = await self._engine.do_action(
            session=session, action="click", text=selector,
        )
        return f"Found: {element_info}\nAction: {click_result}"

    async def smart_fill(
        self, session: str = "", description: str = "", value: str = "",
    ) -> str:
        """Find input field by description and fill it."""
        element_info = await self._analyzer.find_element(
            session=session, description=description,
        )
        selector = self._extract_selector(element_info)
        if not selector:
            return f"[error] Could not identify input for: {description}\nLLM response: {element_info}"

        fill_result = await self._engine.do_action(
            session=session, action="click", text=selector,
        )
        fill_result = await self._engine.do_action(
            session=session, action="fill",
            selector=f"*:focus",
            value=value,
        )
        return f"Found: {element_info}\nFilled with: {value}\nResult: {fill_result}"

    @staticmethod
    def _extract_selector(element_info: str) -> str:
        """Extract usable selector from LLM element identification response."""
        # Try to find a11y element reference like [button "Sign In"]
        match = _A11Y_ELEMENT_RE.search(element_info)
        if match:
            return match.group(2)  # Return the name as text to match

        # Try CSS selector if mentioned
        css_match = re.search(r'(?:selector|css):\s*`?([^`\n]+)`?', element_info, re.IGNORECASE)
        if css_match:
            return css_match.group(1).strip()

        # Fallback: use the raw response trimmed
        clean = element_info.strip()
        if len(clean) < 100:
            return clean
        return ""

    def get_tool_functions(self) -> list[Callable]:
        """Return tool functions for registration."""
        vb = self

        @tool(
            description=(
                "Analyze current web page using AI Vision. "
                "Captures screenshot + accessibility tree, sends to LLM, "
                "returns detailed page description and state analysis."
            )
        )
        async def browser_analyze(session: str = "", question: str = "") -> str:
            return await vb.analyze(session=session, question=question)

        @tool(
            description=(
                "Find a web page element by natural language description using AI Vision. "
                "Example: 'the login button', 'email input field', 'navigation menu'"
            )
        )
        async def browser_find_element(session: str = "", description: str = "") -> str:
            return await vb.find_element(session=session, description=description)

        @tool(
            description=(
                "Find element by description using AI Vision and click it. "
                "Example: description='the Sign In button'"
            )
        )
        async def browser_smart_click(session: str = "", description: str = "") -> str:
            return await vb.smart_click(session=session, description=description)

        @tool(
            description=(
                "Find input field by description using AI Vision and fill it with a value. "
                "Example: description='email field', value='user@example.com'"
            )
        )
        async def browser_smart_fill(
            session: str = "", description: str = "", value: str = "",
        ) -> str:
            return await vb.smart_fill(session=session, description=description, value=value)

        return [browser_analyze, browser_find_element, browser_smart_click, browser_smart_fill]
```

- [ ] **Step 4: Run tests — all 5 should pass**

Run: `python -m pytest tests/tools/test_browser_vision.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/browser_vision.py tests/tools/test_browser_vision.py
git commit -m "feat(browser): add VisionBrowser with smart click/fill using LLM Vision"
```

---

### Task 5: Wire vision tools into BrowserEngine and plugin

**Files:**
- Modify: `src/breadmind/tools/browser_engine.py`
- Modify: `src/breadmind/plugins/builtin/browser/plugin.py`

- [ ] **Step 1: Add vision integration to BrowserEngine**

In `browser_engine.py`, add these imports at the top:

```python
from breadmind.tools.browser_page_analyzer import PageAnalyzer
from breadmind.tools.browser_vision import VisionBrowser
```

Add to `__init__`:

```python
self._page_analyzer: Any = None
self._vision_browser: Any = None
```

Add new method:

```python
def init_vision(self, llm_provider: Any) -> None:
    """Initialize vision layer with an LLM provider."""
    self._page_analyzer = PageAnalyzer(llm_provider, self)
    self._vision_browser = VisionBrowser(self._page_analyzer, self)
```

Modify `get_tool_functions()` to include vision tools:

In the existing return of `get_tool_functions()`, after the 6 base tools, add vision tools if available:

```python
def get_tool_functions(self) -> list[Callable]:
    tools = build_tool_functions(self)
    if self._vision_browser:
        tools.extend(self._vision_browser.get_tool_functions())
    return tools
```

- [ ] **Step 2: Update plugin.py to pass LLM provider**

In `src/breadmind/plugins/builtin/browser/plugin.py`, in the `setup` method, after `self._engine = BrowserEngine(**kwargs)`, add:

```python
# Initialize vision layer if LLM provider is available
llm_provider = getattr(container, "llm_provider", None)
if llm_provider is None:
    try:
        llm_provider = container.get("llm_provider")
    except Exception:
        pass
if llm_provider:
    self._engine.init_vision(llm_provider)
    logger.info("Browser vision layer initialized")
```

- [ ] **Step 3: Commit**

```bash
git add src/breadmind/tools/browser_engine.py src/breadmind/plugins/builtin/browser/plugin.py
git commit -m "feat(browser): wire vision tools into BrowserEngine and plugin"
```
