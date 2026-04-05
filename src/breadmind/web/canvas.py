"""Canvas (A2UI) foundation: agent-driven UI surface system."""
from __future__ import annotations
import json, logging, uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

@dataclass
class CanvasSurface:
    id: str
    session_id: str
    content: str = ""  # HTML/Markdown content
    components: list[dict] = field(default_factory=list)
    created_at: float = 0

class CanvasManager:
    """Manages agent-driven UI surfaces."""

    def __init__(self) -> None:
        self._surfaces: dict[str, CanvasSurface] = {}

    def create_surface(self, session_id: str, content: str = "") -> CanvasSurface:
        surface_id = f"canvas_{uuid.uuid4().hex[:8]}"
        surface = CanvasSurface(id=surface_id, session_id=session_id, content=content)
        self._surfaces[surface_id] = surface
        return surface

    def update_surface(self, surface_id: str, content: str | None = None,
                       components: list[dict] | None = None) -> CanvasSurface | None:
        surface = self._surfaces.get(surface_id)
        if not surface:
            return None
        if content is not None:
            surface.content = content
        if components is not None:
            surface.components = components
        return surface

    def delete_surface(self, surface_id: str) -> bool:
        return self._surfaces.pop(surface_id, None) is not None

    def get_surface(self, surface_id: str) -> CanvasSurface | None:
        return self._surfaces.get(surface_id)

    def list_surfaces(self, session_id: str | None = None) -> list[CanvasSurface]:
        surfaces = list(self._surfaces.values())
        if session_id:
            surfaces = [s for s in surfaces if s.session_id == session_id]
        return surfaces

    def render_surface(self, surface_id: str) -> str:
        """Render surface content as HTML."""
        surface = self._surfaces.get(surface_id)
        if not surface:
            return ""
        # Basic rendering: wrap content in a simple HTML template
        return f"""<!DOCTYPE html>
<html><head><title>BreadMind Canvas</title>
<style>body{{font-family:system-ui;padding:20px;max-width:800px;margin:0 auto}}</style>
</head><body>{surface.content}</body></html>"""
