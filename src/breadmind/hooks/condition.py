"""Conditional filtering for BreadMind hooks.

Public API
----------
    matches_condition(condition, payload) -> bool

Three pattern types are auto-detected:

- Tool pattern (Claude Code compat): ``"Bash(git *)"``
  Matches when ``payload.data["tool_name"]`` equals the tool name AND
  ``payload.data["tool_input"]`` matches the glob pattern inside the parens.
  Without parens (e.g. ``"Bash"``) only the tool name is checked.

- Data field match: ``"data.channel_id=general"``
  Traverses ``payload.data`` using dot-notation and compares the leaf value
  (string equality).

- Event match: ``"event=pre_tool_use"``
  Compares ``payload.event.value`` to the given string.

Composition:
- Pass a list for OR semantics (any match passes).
- Prefix a pattern with ``!`` to negate it.
- Pass ``None`` to always return ``True``.
"""
from __future__ import annotations

import fnmatch
import re
from typing import Any

from breadmind.hooks.events import HookPayload

# Regex to detect "ToolName(...)" or plain "ToolName"
_TOOL_PATTERN_RE = re.compile(r"^([A-Za-z_]\w*)(?:\((.*)?\))?$", re.DOTALL)
_DATA_FIELD_RE = re.compile(r"^data\.([\w.]+)=(.+)$", re.DOTALL)
_EVENT_RE = re.compile(r"^event=(.+)$")


def matches_condition(
    condition: str | list[str] | None,
    payload: HookPayload,
) -> bool:
    """Return *True* when *payload* satisfies *condition*.

    Parameters
    ----------
    condition:
        - ``None``       — always returns ``True``.
        - ``str``        — single pattern (may start with ``!`` to negate).
        - ``list[str]``  — OR composition; returns ``True`` if any entry matches.
    payload:
        The hook payload to test against.
    """
    if condition is None:
        return True

    if isinstance(condition, list):
        return any(_match_single(c, payload) for c in condition)

    return _match_single(condition, payload)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _match_single(pattern: str, payload: HookPayload) -> bool:
    """Evaluate one pattern string (possibly prefixed with ``!``)."""
    if pattern.startswith("!"):
        return not _evaluate(pattern[1:], payload)
    return _evaluate(pattern, payload)


def _evaluate(pattern: str, payload: HookPayload) -> bool:
    """Dispatch to the correct pattern evaluator."""
    # Empty pattern — no match
    if not pattern:
        return False

    # 1. Event match: "event=<value>"
    m = _EVENT_RE.match(pattern)
    if m:
        return payload.event.value == m.group(1)

    # 2. Data field match: "data.<field>=<value>"
    m = _DATA_FIELD_RE.match(pattern)
    if m:
        field_path, expected = m.group(1), m.group(2)
        return _match_data_field(payload.data, field_path, expected)

    # 3. Tool pattern: "ToolName" or "ToolName(glob)"
    m = _TOOL_PATTERN_RE.match(pattern)
    if m:
        tool_name_pattern, arg_pattern = m.group(1), m.group(2)
        return _match_tool(payload, tool_name_pattern, arg_pattern)

    return False


def _match_data_field(data: dict[str, Any], field_path: str, expected: str) -> bool:
    """Traverse *data* using dot-notation and compare leaf to *expected*."""
    keys = field_path.split(".")
    node: Any = data
    for key in keys:
        if not isinstance(node, dict):
            return False
        if key not in node:
            return False
        node = node[key]
    return str(node) == expected if isinstance(node, str) else False


def _match_tool(
    payload: HookPayload,
    tool_name: str,
    arg_pattern: str | None,
) -> bool:
    """Match tool name and (optionally) tool_input via fnmatch glob."""
    actual_tool = payload.data.get("tool_name")
    if actual_tool != tool_name:
        return False

    # Pattern without parens — tool name match only
    if arg_pattern is None:
        return True

    # Pattern with parens — must also match tool_input
    actual_input = payload.data.get("tool_input")
    if actual_input is None:
        return False

    return fnmatch.fnmatch(actual_input, arg_pattern)
