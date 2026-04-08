"""Tests for accessibility tree extraction."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock


def _make_ax_node(role: str, name: str = "", value: str = "",
                  children: list | None = None, **props) -> dict:
    """Helper to build CDP AXNode-like dicts."""
    node = {
        "role": {"value": role},
        "name": {"value": name},
        "properties": [{"name": k, "value": {"value": v}} for k, v in props.items()],
        "children": children or [],
    }
    if value:
        node["value"] = {"value": value}
    return node


async def test_extract_simple_tree():
    from breadmind.tools.browser_a11y import A11yExtractor
    cdp = AsyncMock()
    cdp.send = AsyncMock(return_value={
        "nodes": [
            _make_ax_node("RootWebArea", "Example Page", children=[
                _make_ax_node("heading", "Dashboard", level="1"),
                _make_ax_node("button", "Sign In"),
                _make_ax_node("textbox", "Email", value=""),
            ]),
        ],
    })
    extractor = A11yExtractor(cdp)
    tree = await extractor.extract()
    assert len(tree) > 0


async def test_format_compact():
    from breadmind.tools.browser_a11y import A11yExtractor, AXNode
    nodes = [
        AXNode(role="heading", name="Dashboard", properties={"level": "1"}),
        AXNode(role="button", name="Sign In"),
        AXNode(role="textbox", name="Email", value="user@test.com"),
    ]
    text = A11yExtractor.format_compact(nodes)
    assert '[heading level=1 "Dashboard"]' in text
    assert '[button "Sign In"]' in text
    assert '[textbox "Email" value="user@test.com"]' in text


async def test_format_compact_with_depth():
    from breadmind.tools.browser_a11y import A11yExtractor, AXNode
    parent = AXNode(
        role="navigation", name="Main Nav",
        children=[
            AXNode(role="link", name="Home"),
            AXNode(role="link", name="Settings"),
        ],
    )
    text = A11yExtractor.format_compact([parent])
    assert "[navigation" in text
    assert '  [link "Home"]' in text


async def test_filter_interactive_only():
    from breadmind.tools.browser_a11y import A11yExtractor, AXNode
    nodes = [
        AXNode(role="heading", name="Title"),
        AXNode(role="button", name="Submit"),
        AXNode(role="textbox", name="Name"),
        AXNode(role="paragraph", name="Some text"),
        AXNode(role="link", name="Click here"),
    ]
    filtered = A11yExtractor.filter_interactive(nodes)
    roles = [n.role for n in filtered]
    assert "button" in roles
    assert "textbox" in roles
    assert "link" in roles
    assert "heading" not in roles
    assert "paragraph" not in roles


async def test_max_depth_respected():
    from breadmind.tools.browser_a11y import A11yExtractor
    cdp = AsyncMock()
    deep = _make_ax_node("button", "Deep Button")
    for i in range(5):
        deep = _make_ax_node("section", f"layer-{i}", children=[deep])
    root = _make_ax_node("RootWebArea", "Page", children=[deep])
    cdp.send = AsyncMock(return_value={"nodes": [root]})
    extractor = A11yExtractor(cdp, max_depth=3)
    tree = await extractor.extract()
    text = A11yExtractor.format_compact(tree)
    assert "Deep Button" not in text


async def test_token_estimate():
    from breadmind.tools.browser_a11y import A11yExtractor, AXNode
    nodes = [
        AXNode(role="button", name="OK"),
        AXNode(role="textbox", name="Email", value="test@test.com"),
    ]
    text = A11yExtractor.format_compact(nodes)
    estimate = A11yExtractor.estimate_tokens(text)
    assert estimate > 0
    assert isinstance(estimate, int)
