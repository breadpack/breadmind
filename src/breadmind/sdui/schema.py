"""Component registry and UISpec validation."""
from __future__ import annotations

from breadmind.sdui.spec import Component, UISpec


class SpecValidationError(ValueError):
    pass


KNOWN_COMPONENTS: set[str] = {
    # layout
    "page", "stack", "grid", "split", "tabs",
    # display
    "text", "heading", "markdown", "code", "badge", "progress", "stat", "divider",
    # data
    "table", "list", "tree", "timeline", "kv",
    # interactive
    "button", "form", "field", "select", "confirm",
    # flow
    "dag_view", "step_card", "log_stream", "recovery_panel",
}


def validate_spec(spec: UISpec) -> None:
    _validate_component(spec.root)


def _validate_component(c: Component) -> None:
    if c.type not in KNOWN_COMPONENTS:
        raise SpecValidationError(f"unknown component type: {c.type}")
    if not isinstance(c.props, dict):
        raise SpecValidationError(f"component {c.id} props must be dict")
    for child in c.children:
        _validate_component(child)
