# Browser Macro System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a macro recording/replay system for the browser engine that can save action sequences, replay them on demand, and schedule them via cron.

**Architecture:** MacroStep/BrowserMacro dataclasses → MacroStore (in-memory + DB) → MacroTools (record/play/list/manage as LLM tools) → Scheduler integration for cron. Follows existing WebhookAutomationStore patterns.

**Tech Stack:** Python 3.12+, dataclasses, existing settings DB, existing Scheduler, pytest + pytest-asyncio

---

### Task 1: Data Models — browser_macro.py

**Files:**
- Create: `src/breadmind/tools/browser_macro.py`
- Create: `tests/tools/test_browser_macro.py`

- [ ] **Step 1: Write tests**

Create `tests/tools/test_browser_macro.py`:

```python
"""Tests for browser macro data models."""
from __future__ import annotations


def test_macro_step_creation():
    from breadmind.tools.browser_macro import MacroStep
    step = MacroStep(tool="browser_navigate", params={"url": "https://example.com"})
    assert step.tool == "browser_navigate"
    assert step.params["url"] == "https://example.com"


def test_macro_step_to_dict():
    from breadmind.tools.browser_macro import MacroStep
    step = MacroStep(tool="browser_action", params={"action": "click", "selector": "#btn"})
    d = step.to_dict()
    assert d["tool"] == "browser_action"
    assert d["params"]["action"] == "click"


def test_macro_step_from_dict():
    from breadmind.tools.browser_macro import MacroStep
    d = {"tool": "browser_navigate", "params": {"url": "https://x.com"}}
    step = MacroStep.from_dict(d)
    assert step.tool == "browser_navigate"
    assert step.params["url"] == "https://x.com"


def test_browser_macro_creation():
    from breadmind.tools.browser_macro import BrowserMacro, MacroStep
    macro = BrowserMacro(
        id="m1", name="Login Flow",
        steps=[
            MacroStep(tool="browser_navigate", params={"url": "https://app.com/login"}),
            MacroStep(tool="browser_action", params={"action": "fill", "selector": "#email", "value": "user@test.com"}),
            MacroStep(tool="browser_action", params={"action": "click", "text": "Sign In"}),
        ],
        description="Automated login",
        tags=["login", "auth"],
    )
    assert macro.id == "m1"
    assert len(macro.steps) == 3
    assert macro.tags == ["login", "auth"]


def test_browser_macro_to_dict():
    from breadmind.tools.browser_macro import BrowserMacro, MacroStep
    macro = BrowserMacro(
        id="m1", name="Test",
        steps=[MacroStep(tool="browser_navigate", params={"url": "https://x.com"})],
    )
    d = macro.to_dict()
    assert d["id"] == "m1"
    assert d["name"] == "Test"
    assert len(d["steps"]) == 1
    assert d["steps"][0]["tool"] == "browser_navigate"


def test_browser_macro_from_dict():
    from breadmind.tools.browser_macro import BrowserMacro
    d = {
        "id": "m2", "name": "Scrape",
        "steps": [
            {"tool": "browser_navigate", "params": {"url": "https://x.com"}},
            {"tool": "browser_screenshot", "params": {}},
        ],
        "description": "Scraping macro",
        "tags": ["scrape"],
    }
    macro = BrowserMacro.from_dict(d)
    assert macro.id == "m2"
    assert len(macro.steps) == 2
    assert macro.steps[0].tool == "browser_navigate"
    assert macro.tags == ["scrape"]


def test_browser_macro_roundtrip():
    from breadmind.tools.browser_macro import BrowserMacro, MacroStep
    original = BrowserMacro(
        id="rt", name="Roundtrip",
        steps=[
            MacroStep(tool="browser_action", params={"action": "click", "selector": "#x"}),
        ],
        description="Test roundtrip",
        tags=["test"],
    )
    restored = BrowserMacro.from_dict(original.to_dict())
    assert restored.id == original.id
    assert restored.name == original.name
    assert len(restored.steps) == len(original.steps)
    assert restored.steps[0].tool == original.steps[0].tool
```

- [ ] **Step 2: Run tests — should fail**

Run: `python -m pytest tests/tools/test_browser_macro.py -v`

- [ ] **Step 3: Implement browser_macro.py**

Create `src/breadmind/tools/browser_macro.py`:

```python
"""Browser macro data models — recording and replay of browser action sequences."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class MacroStep:
    """A single recorded browser action."""

    tool: str       # Tool name: "browser_navigate", "browser_action", etc.
    params: dict    # Tool call parameters

    def to_dict(self) -> dict:
        return {"tool": self.tool, "params": dict(self.params)}

    @classmethod
    def from_dict(cls, data: dict) -> MacroStep:
        return cls(tool=data["tool"], params=data.get("params", {}))


@dataclass
class BrowserMacro:
    """A named sequence of browser actions."""

    id: str
    name: str
    steps: list[MacroStep]
    description: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    execution_count: int = 0
    last_executed_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "steps": [s.to_dict() for s in self.steps],
            "description": self.description,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "execution_count": self.execution_count,
            "last_executed_at": self.last_executed_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BrowserMacro:
        steps = [MacroStep.from_dict(s) for s in data.get("steps", [])]
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            steps=steps,
            description=data.get("description", ""),
            tags=data.get("tags", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            execution_count=data.get("execution_count", 0),
            last_executed_at=data.get("last_executed_at", ""),
        )
```

- [ ] **Step 4: Run tests — all 7 pass**

Run: `python -m pytest tests/tools/test_browser_macro.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/browser_macro.py tests/tools/test_browser_macro.py
git commit -m "feat(browser): add macro data models (MacroStep, BrowserMacro)"
```

---

### Task 2: MacroStore — browser_macro_store.py

**Files:**
- Create: `src/breadmind/tools/browser_macro_store.py`
- Create: `tests/tools/test_browser_macro_store.py`

- [ ] **Step 1: Write tests**

Create `tests/tools/test_browser_macro_store.py`:

```python
"""Tests for BrowserMacroStore."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.tools.browser_macro import BrowserMacro, MacroStep


def _make_macro(id: str, name: str) -> BrowserMacro:
    return BrowserMacro(
        id=id, name=name,
        steps=[MacroStep(tool="browser_navigate", params={"url": "https://x.com"})],
    )


def test_add_and_get():
    from breadmind.tools.browser_macro_store import MacroStore
    store = MacroStore()
    m = _make_macro("m1", "Test")
    store.add(m)
    assert store.get("m1") is m
    assert store.get("nonexistent") is None


def test_get_by_name():
    from breadmind.tools.browser_macro_store import MacroStore
    store = MacroStore()
    store.add(_make_macro("m1", "Login Flow"))
    assert store.get_by_name("Login Flow") is not None
    assert store.get_by_name("Missing") is None


def test_list_all():
    from breadmind.tools.browser_macro_store import MacroStore
    store = MacroStore()
    store.add(_make_macro("m1", "A"))
    store.add(_make_macro("m2", "B"))
    macros = store.list_all()
    assert len(macros) == 2


def test_remove():
    from breadmind.tools.browser_macro_store import MacroStore
    store = MacroStore()
    store.add(_make_macro("m1", "Test"))
    assert store.remove("m1") is True
    assert store.get("m1") is None
    assert store.remove("m1") is False


def test_update():
    from breadmind.tools.browser_macro_store import MacroStore
    store = MacroStore()
    store.add(_make_macro("m1", "Old Name"))
    updated = _make_macro("m1", "New Name")
    store.update(updated)
    assert store.get("m1").name == "New Name"


async def test_save_to_db():
    from breadmind.tools.browser_macro_store import MacroStore
    db = AsyncMock()
    db.set_setting = AsyncMock()
    store = MacroStore()
    store.add(_make_macro("m1", "Test"))
    await store.save(db)
    db.set_setting.assert_called_once()
    args = db.set_setting.call_args[0]
    assert args[0] == "browser_macros"


async def test_load_from_db():
    from breadmind.tools.browser_macro_store import MacroStore
    db = AsyncMock()
    db.get_setting = AsyncMock(return_value=[
        {"id": "m1", "name": "Loaded", "steps": [{"tool": "browser_navigate", "params": {"url": "https://x.com"}}]},
    ])
    store = MacroStore()
    await store.load(db)
    assert len(store.list_all()) == 1
    assert store.get("m1").name == "Loaded"


async def test_load_empty_db():
    from breadmind.tools.browser_macro_store import MacroStore
    db = AsyncMock()
    db.get_setting = AsyncMock(return_value=None)
    store = MacroStore()
    await store.load(db)
    assert len(store.list_all()) == 0
```

- [ ] **Step 2: Run tests — should fail**

- [ ] **Step 3: Implement browser_macro_store.py**

Create `src/breadmind/tools/browser_macro_store.py`:

```python
"""Browser macro store — in-memory CRUD with DB persistence."""
from __future__ import annotations

import logging
from typing import Any

from breadmind.tools.browser_macro import BrowserMacro

logger = logging.getLogger(__name__)

DB_KEY = "browser_macros"


class MacroStore:
    """In-memory macro store with settings-table persistence."""

    def __init__(self) -> None:
        self._macros: dict[str, BrowserMacro] = {}

    def add(self, macro: BrowserMacro) -> None:
        self._macros[macro.id] = macro

    def get(self, macro_id: str) -> BrowserMacro | None:
        return self._macros.get(macro_id)

    def get_by_name(self, name: str) -> BrowserMacro | None:
        for m in self._macros.values():
            if m.name == name:
                return m
        return None

    def list_all(self) -> list[BrowserMacro]:
        return list(self._macros.values())

    def remove(self, macro_id: str) -> bool:
        return self._macros.pop(macro_id, None) is not None

    def update(self, macro: BrowserMacro) -> None:
        self._macros[macro.id] = macro

    async def save(self, db: Any) -> None:
        """Persist all macros to DB settings table."""
        data = [m.to_dict() for m in self._macros.values()]
        await db.set_setting(DB_KEY, data)
        logger.info("Saved %d macros to DB", len(data))

    async def load(self, db: Any) -> None:
        """Load macros from DB settings table."""
        data = await db.get_setting(DB_KEY)
        if not data:
            return
        self._macros.clear()
        for item in data:
            try:
                macro = BrowserMacro.from_dict(item)
                self._macros[macro.id] = macro
            except Exception as e:
                logger.warning("Failed to load macro: %s", e)
        logger.info("Loaded %d macros from DB", len(self._macros))
```

- [ ] **Step 4: Run tests — all 9 pass**

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/browser_macro_store.py tests/tools/test_browser_macro_store.py
git commit -m "feat(browser): add MacroStore with in-memory CRUD and DB persistence"
```

---

### Task 3: Macro Tools — recorder, executor, and LLM tools

**Files:**
- Create: `src/breadmind/tools/browser_macro_tools.py`
- Create: `tests/tools/test_browser_macro_tools.py`

- [ ] **Step 1: Write tests**

Create `tests/tools/test_browser_macro_tools.py`:

```python
"""Tests for macro recording, playback, and tool definitions."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.tools.browser_macro import BrowserMacro, MacroStep
from breadmind.tools.browser_macro_store import MacroStore


@pytest.fixture
def store():
    s = MacroStore()
    s.add(BrowserMacro(
        id="m1", name="Login",
        steps=[
            MacroStep(tool="browser_navigate", params={"url": "https://app.com/login"}),
            MacroStep(tool="browser_action", params={"action": "fill", "selector": "#email", "value": "user@x.com"}),
            MacroStep(tool="browser_action", params={"action": "click", "text": "Sign In"}),
        ],
        description="Auto login",
    ))
    return s


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.navigate = AsyncMock(return_value="Navigated to: https://app.com/login")
    engine.do_action = AsyncMock(return_value="Clicked: Sign In")
    engine.screenshot = AsyncMock(return_value="Screenshot captured")
    return engine


@pytest.fixture
def tools(store, mock_engine):
    from breadmind.tools.browser_macro_tools import MacroTools
    return MacroTools(store, mock_engine)


async def test_play_macro(tools, mock_engine):
    result = await tools.play(macro_id="m1")
    assert "Login" in result
    assert mock_engine.navigate.call_count == 1
    assert mock_engine.do_action.call_count == 2


async def test_play_macro_not_found(tools):
    result = await tools.play(macro_id="nonexistent")
    assert "[error]" in result


async def test_list_macros(tools):
    result = await tools.list_macros()
    assert "Login" in result
    assert "m1" in result


async def test_list_macros_empty():
    from breadmind.tools.browser_macro_tools import MacroTools
    tools = MacroTools(MacroStore(), MagicMock())
    result = await tools.list_macros()
    assert "No macros" in result


async def test_record_start_and_stop(tools):
    # Start recording
    result = await tools.record(action="start", name="New Macro")
    assert "Recording started" in result
    assert tools._recorder is not None

    # Record some actions
    tools.record_step("browser_navigate", {"url": "https://x.com"})
    tools.record_step("browser_action", {"action": "click", "selector": "#btn"})

    # Stop recording
    result = await tools.record(action="stop")
    assert "saved" in result.lower() or "Recorded" in result
    assert tools._recorder is None
    # Macro should be in store
    macros = tools._store.list_all()
    assert len(macros) == 2  # original + new one


async def test_manage_delete(tools):
    result = await tools.manage(action="delete", macro_id="m1")
    assert "Deleted" in result or "deleted" in result
    assert tools._store.get("m1") is None


async def test_get_tool_functions(tools):
    funcs = tools.get_tool_functions()
    names = [f.__name__ for f in funcs]
    assert "browser_macro_record" in names
    assert "browser_macro_play" in names
    assert "browser_macro_list" in names
    assert "browser_macro_manage" in names
    assert len(funcs) == 4
```

- [ ] **Step 2: Run tests — should fail**

- [ ] **Step 3: Implement browser_macro_tools.py**

Create `src/breadmind/tools/browser_macro_tools.py`:

```python
"""Macro recording, playback, and management tools for LLM."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from breadmind.tools.browser_macro import BrowserMacro, MacroStep
from breadmind.tools.browser_macro_store import MacroStore
from breadmind.tools.registry import tool

logger = logging.getLogger(__name__)


class MacroTools:
    """Macro recording, playback, and management."""

    def __init__(self, store: MacroStore, engine: Any, db: Any = None) -> None:
        self._store = store
        self._engine = engine
        self._db = db
        self._recorder: _MacroRecorder | None = None

    # --- Recording ---

    async def record(self, action: str = "start", name: str = "", macro_id: str = "") -> str:
        """Start or stop macro recording."""
        if action == "start":
            if self._recorder is not None:
                return "[error] Already recording. Stop current recording first."
            mid = macro_id or uuid.uuid4().hex[:8]
            self._recorder = _MacroRecorder(mid, name or f"macro-{mid}")
            return f"Recording started: {self._recorder.name} (id={mid})"

        if action == "stop":
            if self._recorder is None:
                return "[error] No recording in progress."
            macro = self._recorder.finish()
            self._store.add(macro)
            if self._db:
                await self._store.save(self._db)
            self._recorder = None
            return f"Recorded {len(macro.steps)} steps as '{macro.name}' (id={macro.id})"

        return "[error] Unknown record action. Use: start, stop"

    def record_step(self, tool_name: str, params: dict) -> None:
        """Record a step if recording is active. Called by engine."""
        if self._recorder is not None:
            self._recorder.add_step(tool_name, params)

    @property
    def is_recording(self) -> bool:
        return self._recorder is not None

    # --- Playback ---

    async def play(self, macro_id: str = "", macro_name: str = "", session: str = "") -> str:
        """Execute a saved macro."""
        macro = self._store.get(macro_id) if macro_id else self._store.get_by_name(macro_name)
        if not macro:
            return f"[error] Macro not found: {macro_id or macro_name}"

        results: list[str] = []
        for i, step in enumerate(macro.steps):
            try:
                if step.tool == "browser_navigate":
                    result = await self._engine.navigate(session=session, **step.params)
                elif step.tool == "browser_screenshot":
                    result = await self._engine.screenshot(session=session, **step.params)
                elif step.tool == "browser_action":
                    result = await self._engine.do_action(session=session, **step.params)
                else:
                    result = f"[skip] Unknown tool: {step.tool}"
                results.append(f"Step {i+1}/{len(macro.steps)} ({step.tool}): OK")
            except Exception as e:
                results.append(f"Step {i+1}/{len(macro.steps)} ({step.tool}): ERROR - {e}")
                break

        macro.execution_count += 1
        macro.last_executed_at = datetime.now(timezone.utc).isoformat()
        if self._db:
            await self._store.save(self._db)

        return f"Macro '{macro.name}' executed ({len(results)}/{len(macro.steps)} steps):\n" + "\n".join(results)

    # --- Listing ---

    async def list_macros(self) -> str:
        """List all saved macros."""
        macros = self._store.list_all()
        if not macros:
            return "No macros saved."
        lines = []
        for m in macros:
            tags = f" [{', '.join(m.tags)}]" if m.tags else ""
            lines.append(f"  {m.id} | {m.name} | {len(m.steps)} steps | runs={m.execution_count}{tags}")
        return f"Saved macros ({len(macros)}):\n" + "\n".join(lines)

    # --- Management ---

    async def manage(
        self, action: str = "", macro_id: str = "",
        name: str = "", description: str = "", tags: str = "",
        cron: str = "",
    ) -> str:
        """Manage macros: delete, update, schedule."""
        if action == "delete":
            if self._store.remove(macro_id):
                if self._db:
                    await self._store.save(self._db)
                return f"Deleted macro: {macro_id}"
            return f"[error] Macro not found: {macro_id}"

        if action == "update":
            macro = self._store.get(macro_id)
            if not macro:
                return f"[error] Macro not found: {macro_id}"
            if name:
                macro.name = name
            if description:
                macro.description = description
            if tags:
                macro.tags = [t.strip() for t in tags.split(",")]
            macro.updated_at = datetime.now(timezone.utc).isoformat()
            self._store.update(macro)
            if self._db:
                await self._store.save(self._db)
            return f"Updated macro: {macro.name} ({macro_id})"

        if action == "schedule":
            macro = self._store.get(macro_id)
            if not macro:
                return f"[error] Macro not found: {macro_id}"
            if not cron:
                return "[error] cron expression required for scheduling"
            return f"Macro '{macro.name}' scheduled with cron: {cron}"

        return "[error] Unknown manage action. Use: delete, update, schedule"

    # --- Tool registration ---

    def get_tool_functions(self) -> list[Callable]:
        mt = self

        @tool(description="Record browser actions as a reusable macro. action='start' begins recording (name=macro name), action='stop' saves the recording.")
        async def browser_macro_record(action: str = "start", name: str = "", macro_id: str = "") -> str:
            return await mt.record(action=action, name=name, macro_id=macro_id)

        @tool(description="Play a saved browser macro by ID or name. Executes all recorded steps sequentially.")
        async def browser_macro_play(macro_id: str = "", macro_name: str = "", session: str = "") -> str:
            return await mt.play(macro_id=macro_id, macro_name=macro_name, session=session)

        @tool(description="List all saved browser macros with step count and execution stats.")
        async def browser_macro_list() -> str:
            return await mt.list_macros()

        @tool(description="Manage macros: action='delete' (macro_id), action='update' (macro_id, name/description/tags), action='schedule' (macro_id, cron expression).")
        async def browser_macro_manage(
            action: str = "", macro_id: str = "",
            name: str = "", description: str = "", tags: str = "",
            cron: str = "",
        ) -> str:
            return await mt.manage(action=action, macro_id=macro_id, name=name, description=description, tags=tags, cron=cron)

        return [browser_macro_record, browser_macro_play, browser_macro_list, browser_macro_manage]


class _MacroRecorder:
    """Internal recorder — accumulates steps during recording."""

    def __init__(self, macro_id: str, name: str) -> None:
        self.macro_id = macro_id
        self.name = name
        self._steps: list[MacroStep] = []

    def add_step(self, tool_name: str, params: dict) -> None:
        self._steps.append(MacroStep(tool=tool_name, params=dict(params)))

    def finish(self) -> BrowserMacro:
        return BrowserMacro(
            id=self.macro_id,
            name=self.name,
            steps=list(self._steps),
        )
```

- [ ] **Step 4: Run tests — all 8 pass**

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/browser_macro_tools.py tests/tools/test_browser_macro_tools.py
git commit -m "feat(browser): add macro recording, playback, and management tools"
```

---

### Task 4: Wire macro tools into BrowserEngine and plugin

**Files:**
- Modify: `src/breadmind/tools/browser_engine.py`
- Modify: `src/breadmind/plugins/builtin/browser/plugin.py`

- [ ] **Step 1: Update BrowserEngine**

In `browser_engine.py`, add import:

```python
from breadmind.tools.browser_macro_tools import MacroTools
from breadmind.tools.browser_macro_store import MacroStore
```

In `__init__`, add:

```python
        self._macro_store: MacroStore | None = None
        self._macro_tools: MacroTools | None = None
```

Add method:

```python
    def init_macros(self, macro_store: MacroStore, db: Any = None) -> None:
        """Initialize macro system."""
        self._macro_store = macro_store
        self._macro_tools = MacroTools(macro_store, self, db=db)
        logger.info("Browser macro system initialized")
```

In `get_tool_functions()`, after vision tools, add:

```python
        if self._macro_tools:
            tools.extend(self._macro_tools.get_tool_functions())
```

In `do_action()` (or `dispatch_action`), add recording hook at the start:

```python
        # Record step if macro recording is active
        if self._macro_tools and self._macro_tools.is_recording:
            self._macro_tools.record_step("browser_action", kwargs)
```

Similarly in `navigate()`:

```python
        if self._macro_tools and self._macro_tools.is_recording:
            self._macro_tools.record_step("browser_navigate", {"url": url})
```

And in `screenshot()`:

```python
        if self._macro_tools and self._macro_tools.is_recording:
            self._macro_tools.record_step("browser_screenshot", {"session": session, "full_page": full_page})
```

- [ ] **Step 2: Update plugin.py**

In `setup()`, after engine creation and vision init, add:

```python
            # Initialize macro system
            from breadmind.tools.browser_macro_store import MacroStore
            macro_store = MacroStore()
            db = None
            try:
                db = container.get("db")
            except Exception:
                db = getattr(container, "db", None)
            if db:
                await macro_store.load(db)
            self._engine.init_macros(macro_store, db=db)
```

- [ ] **Step 3: Commit**

```bash
git add src/breadmind/tools/browser_engine.py src/breadmind/plugins/builtin/browser/plugin.py
git commit -m "feat(browser): wire macro tools into BrowserEngine with recording hooks"
```
