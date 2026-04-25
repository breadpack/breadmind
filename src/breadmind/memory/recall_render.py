from __future__ import annotations
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

from breadmind.storage.models import EpisodicNote

_PROMPTS = Path(__file__).parent.parent / "prompts" / "memory"
_jinja = Environment(
    loader=FileSystemLoader(str(_PROMPTS)),
    autoescape=select_autoescape(disabled_extensions=("j2",)),
)


def render_recalled_episodes(notes: list[EpisodicNote]) -> dict | None:
    if not notes:
        return None
    content = _jinja.get_template("recalled_episodes.j2").render(notes=notes)
    return {"role": "system", "content": content}


def render_previous_runs_for_tool(tool_name: str, notes: list[EpisodicNote]) -> list[dict]:
    if not notes:
        return []
    content = _jinja.get_template("previous_runs_for_tool.j2").render(
        tool_name=tool_name, notes=notes,
    )
    return [{"role": "system", "content": content}]
