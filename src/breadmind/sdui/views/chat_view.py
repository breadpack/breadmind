"""Chat view: message list + input form."""
from __future__ import annotations

from typing import Any

from breadmind.sdui.spec import UISpec, Component


async def build(db: Any, *, user_id: str, session_id: str | None = None) -> UISpec:
    return UISpec(
        schema_version=1,
        root=Component(type="page", id="chat", props={"title": "Chat"}, children=[
            Component(type="heading", id="h", props={"value": "BreadMind", "level": 1}),
            Component(type="list", id="messages", props={"variant": "messages"}, children=[]),
            Component(type="form", id="input-form", props={
                "action": {"kind": "chat_input", "session_id": session_id or ""},
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
