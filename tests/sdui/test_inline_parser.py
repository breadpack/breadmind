"""Tests for the inline UISpec parser used to render agent widget responses."""
from __future__ import annotations

from breadmind.sdui.inline_parser import parse_message
from breadmind.sdui.spec import Component


def test_pure_text_returns_single_text_segment():
    segments = parse_message("Hello world")
    assert segments == [("text", "Hello world")]


def test_empty_input_returns_empty_list():
    assert parse_message("") == []


def test_single_widget_block_extracts_component():
    msg = '''여기 비교 표를 보여드릴게요.

```sdui
{"type": "table", "id": "cmp", "props": {"columns": ["A", "B"], "rows": [["1", "2"]]}, "children": []}
```

도움이 되길 바랍니다.'''
    segments = parse_message(msg)
    assert len(segments) == 3
    assert segments[0][0] == "text"
    assert "비교 표" in segments[0][1]
    assert segments[1][0] == "widget"
    widget = segments[1][1]
    assert isinstance(widget, Component)
    assert widget.type == "table"
    assert widget.props["columns"] == ["A", "B"]
    assert segments[2][0] == "text"
    assert "도움이" in segments[2][1]


def test_multiple_widgets_preserve_order():
    msg = '''first
```sdui
{"type": "badge", "id": "b1", "props": {"value": "OK"}, "children": []}
```
middle
```sdui
{"type": "text", "id": "t1", "props": {"value": "hi"}, "children": []}
```
end'''
    segments = parse_message(msg)
    kinds = [s[0] for s in segments]
    assert kinds == ["text", "widget", "text", "widget", "text"]
    assert segments[1][1].type == "badge"
    assert segments[3][1].type == "text"


def test_invalid_json_falls_back_to_text():
    msg = '```sdui\nnot valid json\n```'
    segments = parse_message(msg)
    assert len(segments) == 1
    assert segments[0][0] == "text"
    assert "```sdui" in segments[0][1]


def test_unknown_component_type_falls_back_to_text():
    msg = '```sdui\n{"type": "nonexistent", "id": "x", "props": {}, "children": []}\n```'
    segments = parse_message(msg)
    assert segments[0][0] == "text"
    assert "nonexistent" in segments[0][1]


def test_widget_with_nested_children():
    msg = '''```sdui
{
  "type": "stack",
  "id": "s1",
  "props": {"gap": "md"},
  "children": [
    {"type": "heading", "id": "h", "props": {"value": "Title", "level": 3}, "children": []},
    {"type": "text", "id": "t", "props": {"value": "Body"}, "children": []}
  ]
}
```'''
    segments = parse_message(msg)
    assert len(segments) == 1
    assert segments[0][0] == "widget"
    stack = segments[0][1]
    assert stack.type == "stack"
    assert len(stack.children) == 2
    assert stack.children[0].type == "heading"
    assert stack.children[0].props["value"] == "Title"


def test_case_insensitive_fence_marker():
    msg = '```SDUI\n{"type": "badge", "id": "b", "props": {"value": "X"}, "children": []}\n```'
    segments = parse_message(msg)
    assert segments[0][0] == "widget"
    assert segments[0][1].type == "badge"
