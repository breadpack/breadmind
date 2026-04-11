"""Tests for Phase 1.5: SDUI chat_view CoreAgent integration."""
from __future__ import annotations

from breadmind.flow.event_bus import FlowEventBus
from breadmind.flow.store import FlowEventStore
from breadmind.sdui.actions import ActionHandler
from breadmind.sdui.spec import Component
from breadmind.sdui.views import chat_view


def _walk(component, predicate):
    out = []
    if predicate(component):
        out.append(component)
    for child in component.children:
        out.extend(_walk(child, predicate))
    return out


async def test_chat_view_renders_inline_widget_in_assistant_message(test_db):
    wm = FakeWorkingMemory()
    wm.append("sdui:alice", "user", "비교해줘")
    wm.append(
        "sdui:alice",
        "assistant",
        '여기 비교 결과예요.\n\n```sdui\n{"type":"table","id":"cmp","props":{"columns":["A","B"],"rows":[["1","2"]]},"children":[]}\n```\n\n참고하세요.',
    )
    spec = await chat_view.build(
        test_db, user_id="alice", session_id="sdui:alice", working_memory=wm
    )
    tables = _walk(spec.root, lambda c: c.type == "table")
    assert len(tables) == 1
    assert tables[0].props["columns"] == ["A", "B"]
    # Surrounding text segments should be markdown components
    markdowns = _walk(spec.root, lambda c: c.type == "markdown")
    md_values = [m.props.get("value", "") for m in markdowns]
    assert any("비교 결과" in v for v in md_values)
    assert any("참고하세요" in v for v in md_values)


async def test_user_messages_never_interpret_widget_blocks(test_db):
    """A user pasting raw sdui JSON in their input must NOT be parsed as a widget."""
    wm = FakeWorkingMemory()
    wm.append(
        "sdui:alice",
        "user",
        '```sdui\n{"type":"table","id":"x","props":{},"children":[]}\n```',
    )
    spec = await chat_view.build(
        test_db, user_id="alice", session_id="sdui:alice", working_memory=wm
    )
    tables = _walk(spec.root, lambda c: c.type == "table")
    assert tables == []


async def test_assistant_message_with_invalid_widget_falls_back_to_text(test_db):
    wm = FakeWorkingMemory()
    wm.append("sdui:alice", "assistant", "보세요.\n```sdui\nnot json\n```\n끝")
    spec = await chat_view.build(
        test_db, user_id="alice", session_id="sdui:alice", working_memory=wm
    )
    tables = _walk(spec.root, lambda c: c.type == "table")
    assert tables == []
    markdowns = _walk(spec.root, lambda c: c.type == "markdown")
    md_text = "\n".join(m.props.get("value", "") for m in markdowns)
    assert "not json" in md_text  # raw fence preserved


class FakeWorkingMemory:
    def __init__(self) -> None:
        self._messages: dict[str, list[dict]] = {}

    def get_session_messages(self, session_id: str) -> list[dict]:
        return list(self._messages.get(session_id, []))

    def append(self, session_id: str, role: str, content: str) -> None:
        self._messages.setdefault(session_id, []).append(
            {"role": role, "content": content}
        )


def _find(component, predicate):
    out = []
    if predicate(component):
        out.append(component)
    for ch in component.children:
        out.extend(_find(ch, predicate))
    return out


async def test_chat_view_renders_session_messages(test_db):
    wm = FakeWorkingMemory()
    wm.append("sdui:alice", "user", "hi")
    wm.append("sdui:alice", "assistant", "hello")

    spec = await chat_view.build(
        test_db, user_id="alice", session_id="sdui:alice", working_memory=wm,
    )
    assert spec.root.type == "page"

    markdown_values = [
        c.props.get("value", "")
        for c in _find(spec.root, lambda c: c.type == "markdown")
    ]
    assert "hi" in markdown_values
    assert "hello" in markdown_values


async def test_chat_view_empty_state_without_working_memory(test_db):
    spec = await chat_view.build(test_db, user_id="alice")
    assert spec.root.type == "page"
    # Form must still be present so the user can send a first message.
    forms = _find(spec.root, lambda c: c.type == "form")
    assert forms, "expected input form even with no history"


async def test_chat_view_form_embeds_session_id(test_db):
    spec = await chat_view.build(
        test_db, user_id="alice", session_id="sdui:alice",
    )
    forms = _find(spec.root, lambda c: c.type == "form")
    assert forms
    action = forms[0].props.get("action", {})
    assert action.get("kind") == "chat_input"
    assert action.get("session_id") == "sdui:alice"


async def test_chat_input_action_calls_message_handler(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    try:
        calls: list[tuple[str, str, str]] = []

        async def fake_handler(message, user, channel):
            calls.append((message, user, channel))
            return "the response"

        wm = FakeWorkingMemory()
        handler = ActionHandler(
            bus=bus, message_handler=fake_handler, working_memory=wm,
        )
        result = await handler.handle(
            {
                "kind": "chat_input",
                "session_id": "sdui:alice",
                "values": {"text": "hello world"},
            },
            user_id="alice",
        )
        assert result["ok"] is True
        assert result.get("refresh_view") == "chat_view"
        assert len(calls) == 1
        assert calls[0][0] == "hello world"
        assert calls[0][1] == "alice"
        assert calls[0][2] == "sdui:alice"
    finally:
        await bus.stop()


async def test_chat_input_defaults_session_id_to_user(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    try:
        calls: list[tuple[str, str, str]] = []

        async def fake_handler(message, user, channel):
            calls.append((message, user, channel))
            return ""

        handler = ActionHandler(bus=bus, message_handler=fake_handler)
        result = await handler.handle(
            {"kind": "chat_input", "values": {"text": "hi"}},
            user_id="alice",
        )
        assert result["ok"] is True
        assert calls[0][2] == "sdui:alice"
    finally:
        await bus.stop()


async def test_chat_input_empty_text_is_noop(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    try:
        calls: list[tuple] = []

        async def fake_handler(message, user, channel):
            calls.append((message, user, channel))
            return ""

        handler = ActionHandler(bus=bus, message_handler=fake_handler)
        result = await handler.handle(
            {"kind": "chat_input", "values": {"text": "   "}},
            user_id="alice",
        )
        assert result["ok"] is True
        assert result.get("noop") is True
        assert calls == []
    finally:
        await bus.stop()


async def test_chat_input_falls_back_when_no_handler(test_db):
    store = FlowEventStore(test_db)
    bus = FlowEventBus(store=store, redis=None)
    await bus.start()
    try:
        handler = ActionHandler(bus=bus)
        result = await handler.handle(
            {"kind": "chat_input", "values": {"text": "hi"}},
            user_id="alice",
        )
        assert result["ok"] is True
        assert "deferred" in result or "refresh_view" in result
    finally:
        await bus.stop()
