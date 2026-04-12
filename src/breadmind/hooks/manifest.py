from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from breadmind.hooks.events import HookEvent
from breadmind.hooks.handler import HookHandler, PythonHook, ShellHook

logger = logging.getLogger(__name__)


def _coerce_event(name: str) -> HookEvent | None:
    try:
        return HookEvent(name)
    except ValueError:
        return None


def load_hooks_from_manifest(
    path: Path,
    *,
    resolver: Callable[[str], Callable[..., Any] | None] | None = None,
) -> list[HookHandler]:
    """Read plugin manifest (JSON) and return constructed HookHandlers.

    `resolver` maps a dotted ``module:attr`` spec to the callable implementing
    a Python hook. Plugin loader typically provides an import-based resolver.
    """
    if not path.exists():
        return []
    try:
        manifest = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        logger.error("Invalid plugin manifest %s: %s", path, e)
        return []

    out: list[HookHandler] = []
    for entry in manifest.get("hooks", []) or []:
        name = entry.get("name")
        ev = _coerce_event(entry.get("event", ""))
        if not name or ev is None:
            logger.warning("Skipping hook in %s: missing name or unknown event", path)
            continue

        hook_type = entry.get("type", "shell")
        priority = int(entry.get("priority", 0))
        tool_pattern = entry.get("tool_pattern")
        timeout = float(entry.get("timeout_sec", 5.0 if hook_type == "python" else 10.0))

        if hook_type == "shell":
            command = entry.get("command", "")
            if not command:
                logger.warning("Shell hook %s missing command; skipping", name)
                continue
            out.append(ShellHook(
                name=name, event=ev, command=command,
                priority=priority, tool_pattern=tool_pattern,
                timeout_sec=timeout,
                shell=entry.get("shell", "auto"),
            ))
        elif hook_type == "python":
            entry_spec = entry.get("entry", "")
            if not entry_spec:
                logger.warning("Python hook %s missing entry; skipping", name)
                continue
            resolved = resolver(entry_spec) if resolver else None
            if resolved is None:
                logger.warning(
                    "Python hook %s entry %r could not be resolved; skipping",
                    name, entry_spec,
                )
                continue
            out.append(PythonHook(
                name=name, event=ev, handler=resolved,
                priority=priority, tool_pattern=tool_pattern,
                timeout_sec=timeout,
            ))
        else:
            logger.warning("Unknown hook type %r in %s", hook_type, path)
    return out
