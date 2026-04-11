"""Register ``breadmind_*_setting`` tools into a ``ToolRegistry``.

Thin entry-point module used by the web app wiring (see
``breadmind.web.routes.ui._ensure_projector``) and by integration tests.
Keeping it separate from :mod:`breadmind.tools.settings_tools` avoids
importing FastAPI-side machinery when callers only need the tool callables.
"""
from __future__ import annotations

from typing import Any

from breadmind.tools.settings_tools import build_settings_tools


def register_settings_tools(
    registry: Any,
    *,
    service: Any,
    actor: str = "agent:core",
) -> list[str]:
    """Bind the eight built-in settings tools to ``registry``.

    Returns the list of tool names that were registered (in insertion order).
    """
    tools = build_settings_tools(service=service, actor=actor)
    for fn in tools.values():
        registry.register(fn)
    return list(tools.keys())
