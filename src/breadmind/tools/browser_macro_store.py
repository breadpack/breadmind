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
