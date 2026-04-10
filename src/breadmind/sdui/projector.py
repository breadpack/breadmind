"""UISpecProjector: build views on demand from current DB state."""
from __future__ import annotations

from typing import Any

from breadmind.sdui.spec import UISpec
from breadmind.sdui.views import chat_view, flow_list_view, flow_detail_view


class UISpecProjector:
    def __init__(self, db: Any, bus: Any) -> None:
        self._db = db
        self._bus = bus

    async def build_view(self, view_key: str, **params: Any) -> UISpec:
        if view_key == "chat_view":
            return await chat_view.build(self._db, **params)
        if view_key == "flow_list_view":
            return await flow_list_view.build(self._db, **params)
        if view_key == "flow_detail_view":
            return await flow_detail_view.build(self._db, **params)
        raise ValueError(f"unknown view_key: {view_key}")
