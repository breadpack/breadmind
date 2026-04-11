r"""Parser for inline UISpec widgets embedded in agent responses.

The agent may emit ```sdui ... ``` fenced code blocks containing JSON that
describes a single :class:`Component` (or a list of components). This module
extracts those blocks, validates them against the SDUI schema, and returns
a sequence of message segments where each segment is either:

- ``("text", "...")``: a markdown chunk to render via the ``markdown``
  component, or
- ``("widget", Component)``: a validated component to render directly.

Parsing is intentionally lenient: invalid JSON or unknown component types
fall back to rendering the original fenced block as text so the user still
sees something. The parser never raises.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Iterator

from breadmind.sdui.schema import SpecValidationError, _validate_component
from breadmind.sdui.spec import Component

logger = logging.getLogger(__name__)


_FENCE_RE = re.compile(
    r"```sdui\s*\n(?P<body>.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)


def parse_message(content: str) -> list[tuple[str, object]]:
    """Split ``content`` into ordered ``(kind, value)`` segments.

    ``kind`` is either ``"text"`` (value is a string) or ``"widget"`` (value
    is a :class:`Component`). Returns at least one segment for any non-empty
    input. The order of segments preserves the order they appear in the
    original message so the renderer can show interleaved text + widgets.
    """
    if not content:
        return []

    segments: list[tuple[str, object]] = []
    last_end = 0

    for match in _FENCE_RE.finditer(content):
        # Text before this widget
        text_before = content[last_end : match.start()]
        if text_before.strip():
            segments.append(("text", text_before))

        body = match.group("body")
        widget = _try_parse_widget(body)
        if widget is not None:
            segments.append(("widget", widget))
        else:
            # Fall back to rendering the raw fence as text so the user
            # still sees what the agent tried to do.
            segments.append(("text", match.group(0)))

        last_end = match.end()

    tail = content[last_end:]
    if tail.strip():
        segments.append(("text", tail))

    if not segments:
        # All-whitespace content — emit one empty text segment so callers
        # can rely on a non-empty list.
        segments.append(("text", content))

    return segments


def _try_parse_widget(body: str) -> Component | None:
    """Parse a single fenced JSON body into a validated Component."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.debug("sdui inline block: invalid JSON: %s", exc)
        return None

    if not isinstance(data, dict):
        logger.debug("sdui inline block: top-level must be an object")
        return None

    try:
        component = Component.from_dict(data)
    except (KeyError, TypeError) as exc:
        logger.debug("sdui inline block: malformed component shape: %s", exc)
        return None

    try:
        _validate_component(component)
    except SpecValidationError as exc:
        logger.debug("sdui inline block: rejected by schema: %s", exc)
        return None

    return component


def iter_widgets(content: str) -> Iterator[Component]:
    """Yield only the widget components from ``content``, in order."""
    for kind, value in parse_message(content):
        if kind == "widget" and isinstance(value, Component):
            yield value
