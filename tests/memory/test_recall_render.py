from breadmind.memory.recall_render import (
    render_recalled_episodes, render_previous_runs_for_tool,
)
from breadmind.storage.models import EpisodicNote


def _n(summary, **kw):
    base = dict(content="", keywords=[], tags=[], context_description="",
                summary=summary)
    base.update(kw)
    return EpisodicNote(**base)


def test_recalled_episodes_renders_topk_block():
    notes = [_n("first"), _n("second")]
    msg = render_recalled_episodes(notes)
    assert msg["role"] == "system"
    assert "<recalled_episodes>" in msg["content"]
    assert "first" in msg["content"] and "second" in msg["content"]


def test_render_previous_runs_for_tool_includes_tool_name():
    notes = [_n("ran ok", tool_name="aws_vpc_create", outcome="success")]
    msgs = render_previous_runs_for_tool("aws_vpc_create", notes)
    assert isinstance(msgs, list) and len(msgs) == 1
    assert "aws_vpc_create" in msgs[0]["content"]
    assert "ran ok" in msgs[0]["content"]


def test_render_empty_returns_empty():
    assert render_recalled_episodes([]) is None
    assert render_previous_runs_for_tool("x", []) == []
