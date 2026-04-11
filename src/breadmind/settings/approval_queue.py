"""In-memory queue of pending settings writes awaiting user approval.

Each entry captures the bound callable and its keyword arguments so that
``resolve(id)`` can execute the original intent exactly once.
"""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PendingEntry:
    id: str
    purpose: str
    key: str
    actor: str
    run: Callable[[], Awaitable[Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


class PendingApprovalQueue:
    def __init__(self) -> None:
        self._entries: dict[str, PendingEntry] = {}

    def submit(
        self,
        *,
        purpose: str,
        key: str,
        actor: str,
        run: Callable[[], Awaitable[Any]],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        approval_id = f"approve-{uuid.uuid4().hex[:8]}"
        self._entries[approval_id] = PendingEntry(
            id=approval_id,
            purpose=purpose,
            key=key,
            actor=actor,
            run=run,
            metadata=dict(metadata or {}),
        )
        return approval_id

    async def resolve(self, approval_id: str) -> Any:
        entry = self._entries.pop(approval_id, None)
        if entry is None:
            raise KeyError(approval_id)
        return await entry.run()

    def list_pending(self) -> list[PendingEntry]:
        return list(self._entries.values())
