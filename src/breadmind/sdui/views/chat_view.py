r"""Chat view: message list + input form.

Messages from the agent may contain inline ```sdui``` fenced JSON blocks
describing UISpec components. We parse those out and render them as real
widgets interleaved with the surrounding markdown text. Plain user messages
and agent responses without widgets render exactly as before.
"""
from __future__ import annotations

from typing import Any

from breadmind.sdui.inline_parser import parse_message
from breadmind.sdui.spec import Component, UISpec


async def build(
    db: Any,
    *,
    user_id: str,
    session_id: str | None = None,
    working_memory: Any = None,
) -> UISpec:
    # Default session_id so the form action always carries a usable value.
    # CoreAgent.handle_message stores under f"{user}:{channel}", where channel
    # equals this session_id when dispatched from SDUI. Use the same composite
    # key when reading so the chat view actually sees persisted messages.
    effective_session_id = session_id or f"sdui:{user_id}"
    storage_key = f"{user_id}:{effective_session_id}"

    message_items: list[Component] = []
    if working_memory is not None:
        try:
            raw = working_memory.get_session_messages(storage_key) or []
        except Exception:
            raw = []
        for i, m in enumerate(raw):
            message_items.append(_render_message(i, m))

    if not message_items:
        message_items.append(
            Component(
                type="text",
                id="empty",
                props={"value": "대화를 시작해보세요.", "tone": "muted"},
            )
        )

    return UISpec(
        schema_version=1,
        root=Component(type="page", id="chat", props={"title": "Chat"}, children=[
            Component(type="heading", id="h", props={"value": "BreadMind", "level": 1}),
            Component(
                type="list",
                id="messages",
                props={"variant": "messages"},
                children=message_items,
            ),
            Component(type="form", id="input-form", props={
                "action": {"kind": "chat_input", "session_id": effective_session_id},
            }, children=[
                Component(type="field", id="msg", props={
                    "name": "text",
                    "placeholder": "메시지를 입력하세요 (Shift+Enter 줄바꿈)",
                    "multiline": True,
                    "submit_on_enter": True,
                }),
                Component(type="button", id="send", props={"label": "보내기", "variant": "primary"}),
            ]),
        ]),
    )


def _render_message(index: int, message: dict) -> Component:
    """Render a single chat message into a list card.

    For assistant messages we parse inline ```sdui``` blocks; user messages
    are always plain markdown.
    """
    role = message.get("role", "?")
    content = message.get("content", "") or ""
    tone = "info" if role == "user" else "success"

    children: list[Component] = [
        Component(
            type="badge",
            id=f"role-{index}",
            props={"value": role, "tone": tone},
        ),
    ]

    if role == "user":
        # User input is plain text — never interpret widget blocks.
        children.append(
            Component(
                type="markdown",
                id=f"content-{index}",
                props={"value": content},
            )
        )
    else:
        segments = parse_message(content)
        for seg_idx, (kind, value) in enumerate(segments):
            seg_id = f"seg-{index}-{seg_idx}"
            if kind == "widget" and isinstance(value, Component):
                # Re-id the widget so DOM ids stay unique across messages.
                widget = _reid(value, prefix=seg_id)
                children.append(widget)
            else:
                text_value = value if isinstance(value, str) else str(value)
                children.append(
                    Component(
                        type="markdown",
                        id=seg_id,
                        props={"value": text_value},
                    )
                )

    return Component(
        type="list",
        id=f"msg-{index}",
        props={"variant": "message"},
        children=children,
    )


def _reid(component: Component, *, prefix: str) -> Component:
    """Return a copy of ``component`` with a unique id derived from ``prefix``."""
    new_children = [
        _reid(child, prefix=f"{prefix}-{i}")
        for i, child in enumerate(component.children)
    ]
    return Component(
        type=component.type,
        id=f"{prefix}-{component.id}",
        props=component.props,
        children=new_children,
    )
