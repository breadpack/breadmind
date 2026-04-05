"""Design Mode — agent-assisted UI annotation and editing.

Users can annotate UI elements (via CSS selectors or screenshot coordinates)
with instructions.  The agent interprets annotations and generates code
changes for the frontend.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class UIAnnotation:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    element_selector: str = ""  # CSS selector
    annotation_text: str = ""
    annotation_type: str = "comment"  # comment, fix, improve, remove
    screenshot_ref: str | None = None
    coordinates: tuple[int, int] | None = None  # x, y on screenshot


_VALID_TYPES = {"comment", "fix", "improve", "remove"}


class DesignMode:
    """Agent-assisted UI design mode.

    Users can annotate UI elements (via CSS selectors or screenshot coords)
    with instructions.  The agent interprets annotations and generates
    code changes for the frontend.
    """

    def __init__(self) -> None:
        self._annotations: list[UIAnnotation] = []
        self._active = False

    def activate(self) -> None:
        self._active = True

    def deactivate(self) -> None:
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def add_annotation(
        self,
        selector: str = "",
        text: str = "",
        annotation_type: str = "comment",
        coordinates: tuple[int, int] | None = None,
    ) -> UIAnnotation:
        """Add a UI annotation.  At least one of selector or coordinates required."""
        if not selector and coordinates is None:
            raise ValueError("Either selector or coordinates must be provided")
        if annotation_type not in _VALID_TYPES:
            raise ValueError(
                f"Invalid annotation type {annotation_type!r}. "
                f"Valid: {', '.join(sorted(_VALID_TYPES))}"
            )

        annotation = UIAnnotation(
            element_selector=selector,
            annotation_text=text,
            annotation_type=annotation_type,
            coordinates=coordinates,
        )
        self._annotations.append(annotation)
        return annotation

    def get_annotations(
        self, annotation_type: str | None = None
    ) -> list[UIAnnotation]:
        if annotation_type is None:
            return list(self._annotations)
        return [a for a in self._annotations if a.annotation_type == annotation_type]

    def remove_annotation(self, annotation_id: str) -> bool:
        for i, a in enumerate(self._annotations):
            if a.id == annotation_id:
                self._annotations.pop(i)
                return True
        return False

    def clear(self) -> None:
        self._annotations.clear()

    def generate_prompt(self) -> str:
        """Generate a structured prompt from all annotations for the agent."""
        if not self._annotations:
            return "No UI annotations to process."

        lines = ["The following UI annotations need to be addressed:\n"]
        for i, ann in enumerate(self._annotations, 1):
            target = ann.element_selector or f"coordinates ({ann.coordinates})"
            lines.append(
                f"{i}. [{ann.annotation_type.upper()}] Target: {target}\n"
                f"   Instruction: {ann.annotation_text}"
            )
        return "\n".join(lines)
