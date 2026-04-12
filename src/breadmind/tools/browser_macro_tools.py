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
                    await self._engine.navigate(session=session, **step.params)
                elif step.tool == "browser_screenshot":
                    await self._engine.screenshot(session=session, **step.params)
                elif step.tool == "browser_action":
                    await self._engine.do_action(session=session, **step.params)
                else:
                    pass
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
