from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from breadmind.hooks.events import HookEvent
from breadmind.hooks.handler import HookHandler, PythonHook, ShellHook
from breadmind.hooks.http_hook import HttpHook
from breadmind.hooks.prompt_hook import PromptHook
from breadmind.hooks.agent_hook import AgentHook

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
        elif hook_type == "prompt":
            prompt_text = entry.get("prompt", "")
            if not prompt_text:
                logger.warning("Prompt hook %s missing prompt; skipping", name)
                continue
            out.append(PromptHook(
                name=name, event=ev, prompt=prompt_text,
                priority=priority, tool_pattern=tool_pattern,
                timeout_sec=timeout,
                provider=entry.get("provider"),
                model=entry.get("model"),
                if_condition=entry.get("if"),
            ))
        elif hook_type == "agent":
            prompt_text = entry.get("prompt", "")
            if not prompt_text:
                logger.warning("Agent hook %s missing prompt; skipping", name)
                continue
            out.append(AgentHook(
                name=name, event=ev, prompt=prompt_text,
                priority=priority, tool_pattern=tool_pattern,
                timeout_sec=timeout,
                max_turns=int(entry.get("max_turns", 3)),
                allowed_tools=entry.get("allowed_tools", "readonly"),
                if_condition=entry.get("if"),
            ))
        elif hook_type == "http":
            url = entry.get("url", "")
            if not url:
                logger.warning("HTTP hook %s missing url; skipping", name)
                continue
            out.append(HttpHook(
                name=name, event=ev, url=url,
                priority=priority, tool_pattern=tool_pattern,
                timeout_sec=timeout,
                headers=entry.get("headers", {}),
                method=entry.get("method", "POST"),
                if_condition=entry.get("if"),
            ))
        else:
            logger.warning("Unknown hook type %r in %s", hook_type, path)
    return out
