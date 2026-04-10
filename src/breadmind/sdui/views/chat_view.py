"""Chat view: message list + input form."""
from __future__ import annotations

from typing import Any

from breadmind.sdui.spec import UISpec, Component


async def build(
    db: Any,
    *,
    user_id: str,
    session_id: str | None = None,
    working_memory: Any = None,
) -> UISpec:
    # Default session_id so the form action always carries a usable value.
    effective_session_id = session_id or f"sdui:{user_id}"

    message_items: list[Component] = []
    if working_memory is not None:
        try:
            raw = working_memory.get_session_messages(effective_session_id) or []
        except Exception:
            raw = []
        for i, m in enumerate(raw):
            role = m.get("role", "?")
            content = m.get("content", "") or ""
            tone = "info" if role == "user" else "success"
            message_items.append(
                Component(
                    type="list",
                    id=f"msg-{i}",
                    props={"variant": "message"},
                    children=[
                        Component(
                            type="badge",
                            id=f"role-{i}",
                            props={"value": role, "tone": tone},
                        ),
                        Component(
                            type="markdown",
                            id=f"content-{i}",
                            props={"value": content},
                        ),
                    ],
                )
            )

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
                    "placeholder": "메시지를 입력하세요",
                    "multiline": True,
                }),
                Component(type="button", id="send", props={"label": "보내기", "variant": "primary"}),
            ]),
        ]),
    )
