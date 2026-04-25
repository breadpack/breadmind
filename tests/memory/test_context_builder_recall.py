"""T12: ContextBuilder weighted recall tests.

These tests pin the per-turn recall path that ContextBuilder injects into the
LLM message list right after the system prompt and before user/assistant
history. The recall path is opt-in via the ``episodic_store`` kwarg and is
gated by the ``BREADMIND_EPISODIC_RECALL_TURN_K`` env var.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from breadmind.memory.context_builder import ContextBuilder
from breadmind.storage.models import EpisodicNote


def _note(summary: str, **kw) -> EpisodicNote:
    base = dict(
        content="",
        keywords=[],
        tags=[],
        context_description="",
        summary=summary,
    )
    base.update(kw)
    return EpisodicNote(**base)


@pytest.mark.asyncio
async def test_top_k_limit(monkeypatch):
    """``BREADMIND_EPISODIC_RECALL_TURN_K`` caps the per-turn search ``limit``."""
    monkeypatch.setenv("BREADMIND_EPISODIC_RECALL_TURN_K", "2")

    store = AsyncMock()
    store.search.return_value = [_note(f"n{i}") for i in range(5)]

    cb = ContextBuilder(working_memory=MagicMock(), episodic_store=store)
    await cb.build_recalled_episodes(user_id="alice", message="what about region?")

    assert store.search.await_count == 1
    assert store.search.await_args.kwargs["limit"] == 2


@pytest.mark.asyncio
async def test_returns_system_message_when_notes_present():
    """Non-empty store result ⇒ ``build_recalled_episodes`` returns a system
    message whose content includes the rendered note summary."""
    store = AsyncMock()
    store.search.return_value = [_note("prev fact about region")]

    cb = ContextBuilder(working_memory=MagicMock(), episodic_store=store)
    msg = await cb.build_recalled_episodes(user_id="alice", message="region?")

    assert msg is not None
    assert msg["role"] == "system"
    assert "prev fact" in msg["content"]


@pytest.mark.asyncio
async def test_search_failure_returns_none():
    """If the store raises, the method must swallow and return ``None`` so the
    LLM call is never blocked by recall failures."""
    store = AsyncMock()
    store.search.side_effect = RuntimeError("recall blew up")

    cb = ContextBuilder(working_memory=MagicMock(), episodic_store=store)
    msg = await cb.build_recalled_episodes(user_id="alice", message="region?")

    assert msg is None
