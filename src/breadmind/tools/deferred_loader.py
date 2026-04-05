"""Deferred tool schema loading to reduce LLM context usage."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from breadmind.tools.registry import ToolRegistry

from breadmind.llm.base import ToolDefinition


@dataclass
class DeferredToolEntry:
    """Lightweight tool entry: name + description only."""

    name: str
    description: str
    source: str  # "builtin" or "mcp:<server>"


class DeferredToolLoader:
    """Manages deferred loading of tool schemas to reduce context usage."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._loaded_schemas: set[str] = set()

    def get_deferred_list(self) -> list[DeferredToolEntry]:
        """Get lightweight list of all tools (name + description only)."""
        entries: list[DeferredToolEntry] = []
        for defn in self._registry.get_all_definitions():
            source = self._registry.get_tool_source(defn.name)
            entries.append(
                DeferredToolEntry(
                    name=defn.name,
                    description=defn.description,
                    source=source,
                )
            )
        return entries

    def get_full_schemas(self, tool_names: list[str]) -> list[ToolDefinition]:
        """Fetch full schemas for requested tools. Marks them as loaded."""
        results: list[ToolDefinition] = []
        all_defs = {d.name: d for d in self._registry.get_all_definitions()}
        for name in tool_names:
            defn = all_defs.get(name)
            if defn is not None:
                results.append(defn)
                self._loaded_schemas.add(name)
        return results

    def get_active_schemas(self) -> list[ToolDefinition]:
        """Get full schemas for all currently loaded tools."""
        all_defs = {d.name: d for d in self._registry.get_all_definitions()}
        return [
            all_defs[name]
            for name in self._loaded_schemas
            if name in all_defs
        ]

    def build_deferred_context(self) -> str:
        """Build a text block listing deferred tools for LLM context.

        Format: 'Available tools (use tool_search to get full schema):\\n- name: description\\n...'
        Only includes tools NOT yet loaded.
        """
        entries = self.get_deferred_list()
        deferred = [e for e in entries if e.name not in self._loaded_schemas]
        if not deferred:
            return ""
        lines = ["Available tools (use tool_search to get full schema):"]
        for entry in deferred:
            lines.append(f"- {entry.name}: {entry.description}")
        return "\n".join(lines)

    def mark_loaded(self, tool_names: list[str]) -> None:
        """Mark tools as having their full schema sent to LLM."""
        self._loaded_schemas.update(tool_names)

    def reset(self) -> None:
        """Reset loaded state (e.g., on new session)."""
        self._loaded_schemas.clear()

    @property
    def context_savings_ratio(self) -> float:
        """Ratio of schema bytes saved by deferring.

        Returns a value between 0.0 (no savings) and 1.0 (all deferred).
        """
        all_defs = self._registry.get_all_definitions()
        if not all_defs:
            return 0.0

        total_bytes = 0
        loaded_bytes = 0
        for defn in all_defs:
            schema_size = len(json.dumps(defn.parameters))
            total_bytes += schema_size
            if defn.name in self._loaded_schemas:
                loaded_bytes += schema_size

        if total_bytes == 0:
            return 0.0
        return 1.0 - (loaded_bytes / total_bytes)
