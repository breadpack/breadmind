"""Customizable keybinding management for the BreadMind CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Keybinding:
    key: str  # e.g., "ctrl+k", "escape", "ctrl+shift+p"
    action: str  # e.g., "compact", "new_conversation", "toggle_plan"
    context: str = ""  # e.g., "chat", "plan", "global"


DEFAULT_KEYBINDINGS: list[Keybinding] = [
    Keybinding("ctrl+c", "cancel", "global"),
    Keybinding("ctrl+l", "clear", "global"),
    Keybinding("ctrl+o", "compact", "chat"),
    Keybinding("ctrl+n", "new_conversation", "chat"),
    Keybinding("ctrl+p", "toggle_plan", "chat"),
    Keybinding("escape", "exit_mode", "plan"),
    Keybinding("ctrl+shift+p", "command_palette", "global"),
]


class KeybindingManager:
    """Manages customizable keybindings loaded from config file."""

    def __init__(self, config_path: Path | None = None) -> None:
        if config_path is None:
            config_path = Path.home() / ".breadmind" / "keybindings.json"
        self._config_path = config_path
        self._bindings: list[Keybinding] = []
        self._reset_to_defaults()

    def _reset_to_defaults(self) -> None:
        self._bindings = [
            Keybinding(kb.key, kb.action, kb.context)
            for kb in DEFAULT_KEYBINDINGS
        ]

    def load(self) -> None:
        """Load user keybindings, merging with defaults.

        User bindings override defaults when they share the same
        (action, context) pair.
        """
        if not self._config_path.is_file():
            return
        try:
            raw = json.loads(self._config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(raw, list):
            return

        user_bindings: list[Keybinding] = []
        for entry in raw:
            if isinstance(entry, dict) and "key" in entry and "action" in entry:
                user_bindings.append(
                    Keybinding(
                        key=entry["key"],
                        action=entry["action"],
                        context=entry.get("context", ""),
                    )
                )

        # User bindings override defaults that share the same (action, context)
        user_keys = {(b.action, b.context) for b in user_bindings}
        merged = [b for b in self._bindings if (b.action, b.context) not in user_keys]
        merged.extend(user_bindings)
        self._bindings = merged

    def get_action(self, key: str, context: str = "global") -> str | None:
        """Look up action for a key press in a given context."""
        key_lower = key.lower()
        # Try exact context first, then empty context as fallback
        for binding in self._bindings:
            if binding.key.lower() == key_lower and binding.context == context:
                return binding.action
        for binding in self._bindings:
            if binding.key.lower() == key_lower and binding.context == "":
                return binding.action
        return None

    def set_binding(
        self, key: str, action: str, context: str = "global"
    ) -> None:
        """Set or update a keybinding."""
        for binding in self._bindings:
            if binding.action == action and binding.context == context:
                binding.key = key
                return
        self._bindings.append(Keybinding(key=key, action=action, context=context))

    def save(self) -> None:
        """Persist current keybindings to config file."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {"key": b.key, "action": b.action, "context": b.context}
            for b in self._bindings
        ]
        self._config_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def list_bindings(self, context: str | None = None) -> list[Keybinding]:
        """List keybindings, optionally filtered by context."""
        if context is None:
            return list(self._bindings)
        return [b for b in self._bindings if b.context == context]
