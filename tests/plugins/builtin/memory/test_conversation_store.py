"""Tests for ConversationStore -- file mode, PG mode (mocked), and MessageLoopAgent integration."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from breadmind.core.protocols import AgentContext, Message
from breadmind.core.protocols.provider import ToolCallRequest
from breadmind.plugins.builtin.memory.conversation_store import (
    ConversationMeta,
    ConversationStore,
    _dict_to_message,
    _message_to_dict,
)


# ── Helpers ─────────────────────────────────────────────────────────


def _make_pool_mock():
    """Create a mock asyncpg pool with acquire() context manager."""
    pool = MagicMock()
    conn = AsyncMock()

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = cm
    pool.close = AsyncMock()

    return pool, conn


def _sample_messages() -> list[Message]:
    return [
        Message(role="system", content="You are helpful."),
        Message(role="user", content="Hello world"),
        Message(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCallRequest(id="tc1", name="shell", arguments={"cmd": "ls"}),
            ],
        ),
        Message(role="tool", content="file1.py", tool_call_id="tc1"),
        Message(role="assistant", content="Here are your files."),
    ]


def _sample_meta(session_id: str = "sess-1") -> ConversationMeta:
    now = datetime.now(timezone.utc)
    return ConversationMeta(
        session_id=session_id,
        user="alice",
        channel="web",
        title="Hello world",
        created_at=now,
        updated_at=now,
        message_count=5,
        total_tokens=100,
    )


# ── Serialisation ───────────────────────────────────────────────────


class TestMessageSerialisation:
    def test_roundtrip_simple_message(self):
        msg = Message(role="user", content="hi")
        d = _message_to_dict(msg)
        restored = _dict_to_message(d)
        assert restored.role == "user"
        assert restored.content == "hi"
        assert restored.tool_calls == []

    def test_roundtrip_tool_call_message(self):
        msg = Message(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCallRequest(id="tc1", name="shell", arguments={"cmd": "ls"}),
            ],
        )
        d = _message_to_dict(msg)
        assert d["tool_calls"] == [{"id": "tc1", "name": "shell", "arguments": {"cmd": "ls"}}]
        restored = _dict_to_message(d)
        assert len(restored.tool_calls) == 1
        assert restored.tool_calls[0].name == "shell"
        assert restored.content is None

    def test_roundtrip_tool_result_message(self):
        msg = Message(role="tool", content="output", tool_call_id="tc1")
        d = _message_to_dict(msg)
        restored = _dict_to_message(d)
        assert restored.tool_call_id == "tc1"
        assert restored.content == "output"


# ── File mode ───────────────────────────────────────────────────────


class TestFileMode:
    @pytest.fixture
    def store(self, tmp_path):
        return ConversationStore(file_dir=str(tmp_path))

    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self, store):
        msgs = _sample_messages()
        meta = _sample_meta()
        await store.save_conversation("sess-1", msgs, meta)

        loaded = await store.load_conversation("sess-1")
        assert loaded is not None
        assert len(loaded) == len(msgs)
        assert loaded[0].role == "system"
        assert loaded[1].content == "Hello world"
        # Tool call preserved
        assert len(loaded[2].tool_calls) == 1
        assert loaded[2].tool_calls[0].name == "shell"
        # Tool result preserved
        assert loaded[3].tool_call_id == "tc1"

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, store):
        result = await store.load_conversation("no-such-session")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_conversations_recent_first(self, store):
        for i in range(3):
            meta = _sample_meta(f"sess-{i}")
            meta.title = f"Conversation {i}"
            await store.save_conversation(
                f"sess-{i}", [Message(role="user", content=f"msg {i}")], meta,
            )

        items = await store.list_conversations()
        assert len(items) == 3
        # Most recently saved should be first
        assert items[0].session_id == "sess-2"

    @pytest.mark.asyncio
    async def test_list_conversations_filter_by_user(self, store):
        meta_a = _sample_meta("sess-a")
        meta_a.user = "alice"
        meta_b = _sample_meta("sess-b")
        meta_b.user = "bob"
        await store.save_conversation("sess-a", [Message(role="user", content="a")], meta_a)
        await store.save_conversation("sess-b", [Message(role="user", content="b")], meta_b)

        items = await store.list_conversations(user="alice")
        assert len(items) == 1
        assert items[0].user == "alice"

    @pytest.mark.asyncio
    async def test_search_by_title(self, store):
        meta = _sample_meta("sess-1")
        meta.title = "Kubernetes pod troubleshooting"
        await store.save_conversation("sess-1", [Message(role="user", content="x")], meta)

        results = await store.search_conversations("kubernetes")
        assert len(results) == 1
        assert results[0].session_id == "sess-1"

    @pytest.mark.asyncio
    async def test_search_no_match(self, store):
        meta = _sample_meta("sess-1")
        meta.title = "Hello"
        await store.save_conversation("sess-1", [Message(role="user", content="x")], meta)

        results = await store.search_conversations("nonexistent")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_delete_conversation(self, store):
        meta = _sample_meta("sess-1")
        await store.save_conversation("sess-1", [Message(role="user", content="x")], meta)

        assert await store.delete_conversation("sess-1") is True
        assert await store.load_conversation("sess-1") is None
        assert await store.delete_conversation("sess-1") is False

    @pytest.mark.asyncio
    async def test_append_message(self, store):
        # First create a conversation via save_conversation
        meta = _sample_meta("sess-1")
        await store.save_conversation(
            "sess-1", [Message(role="user", content="first")], meta,
        )
        # Append
        await store.save_message("sess-1", Message(role="assistant", content="reply"))
        loaded = await store.load_conversation("sess-1")
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded[1].content == "reply"


# ── No-store mode ──────────────────────────────────────────────────


class TestNoStoreMode:
    @pytest.mark.asyncio
    async def test_all_ops_are_noop(self):
        store = ConversationStore()
        assert await store.load_conversation("x") is None
        assert await store.list_conversations() == []
        assert await store.search_conversations("x") == []
        assert await store.delete_conversation("x") is False
        # Should not raise
        await store.save_message("x", Message(role="user", content="hi"))
        await store.save_conversation(
            "x", [Message(role="user", content="hi")], _sample_meta("x"),
        )


# ── PG mode (mocked) ───────────────────────────────────────────────


class TestPgMode:
    def _make_store_with_mock(self):
        from breadmind.plugins.builtin.memory.pg_backend import PgMemoryBackend
        backend = PgMemoryBackend(dsn="postgresql://test")
        pool, conn = _make_pool_mock()
        backend._pool = pool
        store = ConversationStore(backend=backend)
        return store, conn

    @pytest.mark.asyncio
    async def test_save_conversation_executes_sql(self):
        store, conn = self._make_store_with_mock()
        msgs = _sample_messages()
        meta = _sample_meta("sess-1")

        await store.save_conversation("sess-1", msgs, meta)

        # Expect: 1 upsert meta + 1 delete old msgs + 5 inserts
        calls = conn.execute.call_args_list
        assert any("INSERT INTO v2_conversations" in str(c) for c in calls)
        assert any("DELETE FROM v2_conversation_messages" in str(c) for c in calls)
        msg_inserts = [c for c in calls if "INSERT INTO v2_conversation_messages" in str(c)]
        assert len(msg_inserts) == 5

    @pytest.mark.asyncio
    async def test_load_conversation_returns_messages(self):
        store, conn = self._make_store_with_mock()
        conn.fetch.return_value = [
            {
                "role": "user", "content": "hello", "tool_calls": None,
                "tool_call_id": None, "name": None, "is_meta": False,
            },
            {
                "role": "assistant", "content": "hi",
                "tool_calls": json.dumps([{"id": "t1", "name": "shell", "arguments": {}}]),
                "tool_call_id": None, "name": None, "is_meta": False,
            },
        ]

        loaded = await store.load_conversation("sess-1")
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded[0].role == "user"
        assert len(loaded[1].tool_calls) == 1

    @pytest.mark.asyncio
    async def test_load_empty_returns_none(self):
        store, conn = self._make_store_with_mock()
        conn.fetch.return_value = []

        loaded = await store.load_conversation("sess-1")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_list_conversations(self):
        store, conn = self._make_store_with_mock()
        now = datetime.now(timezone.utc)
        conn.fetch.return_value = [
            {
                "session_id": "s1", "user_id": "alice", "channel": "web",
                "title": "Conv 1", "created_at": now, "updated_at": now,
                "message_count": 3, "total_tokens": 50,
            },
        ]

        items = await store.list_conversations(user="alice", limit=10)
        assert len(items) == 1
        assert items[0].session_id == "s1"
        # SQL should contain user filter
        sql = conn.fetch.call_args[0][0]
        assert "user_id = $1" in sql

    @pytest.mark.asyncio
    async def test_list_all_conversations(self):
        store, conn = self._make_store_with_mock()
        conn.fetch.return_value = []

        await store.list_conversations()
        sql = conn.fetch.call_args[0][0]
        assert "user_id" not in sql or "WHERE user_id" not in sql

    @pytest.mark.asyncio
    async def test_delete_conversation_returns_true(self):
        store, conn = self._make_store_with_mock()
        conn.execute.return_value = "DELETE 1"

        assert await store.delete_conversation("sess-1") is True
        sql = conn.execute.call_args[0][0]
        assert "DELETE FROM v2_conversations" in sql

    @pytest.mark.asyncio
    async def test_delete_conversation_returns_false(self):
        store, conn = self._make_store_with_mock()
        conn.execute.return_value = "DELETE 0"

        assert await store.delete_conversation("nonexistent") is False

    @pytest.mark.asyncio
    async def test_search_conversations(self):
        store, conn = self._make_store_with_mock()
        now = datetime.now(timezone.utc)
        conn.fetch.return_value = [
            {
                "session_id": "s1", "user_id": "alice", "channel": "",
                "title": "K8s debug", "created_at": now, "updated_at": now,
                "message_count": 2, "total_tokens": 30,
            },
        ]

        results = await store.search_conversations("K8s")
        assert len(results) == 1
        sql = conn.fetch.call_args[0][0]
        assert "ILIKE" in sql

    @pytest.mark.asyncio
    async def test_append_message(self):
        store, conn = self._make_store_with_mock()
        conn.fetchval.return_value = 3

        await store.save_message("sess-1", Message(role="user", content="new msg"))
        calls = conn.execute.call_args_list
        insert_calls = [c for c in calls if "INSERT INTO v2_conversation_messages" in str(c)]
        assert len(insert_calls) == 1
        # seq should be the value from fetchval
        assert insert_calls[0][0][2] == 3  # seq arg

    @pytest.mark.asyncio
    async def test_ensure_tables(self):
        store, conn = self._make_store_with_mock()
        await store.ensure_tables()
        sql = conn.execute.call_args[0][0]
        assert "CREATE TABLE IF NOT EXISTS v2_conversations" in sql
        assert "CREATE TABLE IF NOT EXISTS v2_conversation_messages" in sql


# ── MessageLoopAgent integration ────────────────────────────────────


class TestMessageLoopAgentConversationIntegration:
    def _make_agent(self, conv_store=None):
        from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent
        from breadmind.plugins.builtin.safety.guard import SafetyGuard

        provider = AsyncMock()
        provider.supports_feature.return_value = False
        provider.chat = AsyncMock()

        prompt_builder = MagicMock()
        prompt_builder.build.return_value = [MagicMock(content="system prompt")]

        tool_registry = MagicMock()
        tool_registry.get_schemas.return_value = []

        safety = SafetyGuard()

        agent = MessageLoopAgent(
            provider=provider,
            prompt_builder=prompt_builder,
            tool_registry=tool_registry,
            safety_guard=safety,
            max_turns=3,
            conversation_store=conv_store,
        )
        return agent, provider

    @pytest.mark.asyncio
    async def test_resume_loads_existing_conversation(self):
        conv_store = AsyncMock(spec=ConversationStore)
        conv_store.load_conversation = AsyncMock(return_value=[
            Message(role="system", content="system prompt"),
            Message(role="user", content="previous question"),
            Message(role="assistant", content="previous answer"),
        ])
        conv_store.save_conversation = AsyncMock()

        agent, provider = self._make_agent(conv_store)

        # Provider returns a simple response (no tool calls)
        from breadmind.core.protocols import LLMResponse, TokenUsage
        provider.chat.return_value = LLMResponse(
            content="follow-up answer",
            tool_calls=[],
            usage=TokenUsage(input_tokens=10, output_tokens=5),
            stop_reason="end_turn",
        )

        ctx = AgentContext(user="alice", channel="web", session_id="sess-1", resume=True)
        resp = await agent.handle_message("follow-up question", ctx)

        assert resp.content == "follow-up answer"
        # Should have loaded the conversation
        conv_store.load_conversation.assert_awaited_once_with("sess-1")
        # Conversation saved with all messages (3 restored + 1 new user + 1 assistant reply)
        conv_store.save_conversation.assert_awaited_once()
        save_call = conv_store.save_conversation.call_args
        saved_messages = save_call[0][1]  # positional arg: messages
        assert len(saved_messages) == 5
        assert saved_messages[0].role == "system"
        assert saved_messages[3].role == "user"
        assert saved_messages[3].content == "follow-up question"
        assert saved_messages[4].role == "assistant"
        assert saved_messages[4].content == "follow-up answer"

    @pytest.mark.asyncio
    async def test_no_store_works_normally(self):
        """When conversation_store is None, existing behavior is preserved."""
        agent, provider = self._make_agent(conv_store=None)

        from breadmind.core.protocols import LLMResponse, TokenUsage
        provider.chat.return_value = LLMResponse(
            content="response",
            tool_calls=[],
            usage=TokenUsage(input_tokens=10, output_tokens=5),
            stop_reason="end_turn",
        )

        ctx = AgentContext(user="alice", channel="web", session_id="sess-1")
        resp = await agent.handle_message("hello", ctx)
        assert resp.content == "response"

    @pytest.mark.asyncio
    async def test_resume_false_does_not_load(self):
        """When resume=False, conversation is not loaded even if store exists."""
        conv_store = AsyncMock(spec=ConversationStore)
        conv_store.load_conversation = AsyncMock()
        conv_store.save_conversation = AsyncMock()

        agent, provider = self._make_agent(conv_store)

        from breadmind.core.protocols import LLMResponse, TokenUsage
        provider.chat.return_value = LLMResponse(
            content="fresh response",
            tool_calls=[],
            usage=TokenUsage(input_tokens=10, output_tokens=5),
            stop_reason="end_turn",
        )

        ctx = AgentContext(user="alice", channel="web", session_id="sess-1", resume=False)
        resp = await agent.handle_message("hello", ctx)
        assert resp.content == "fresh response"
        conv_store.load_conversation.assert_not_awaited()
        # But conversation IS saved
        conv_store.save_conversation.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_persist_failure_does_not_crash(self):
        """If save_conversation raises, the agent should still return a response."""
        conv_store = AsyncMock(spec=ConversationStore)
        conv_store.load_conversation = AsyncMock(return_value=None)
        conv_store.save_conversation = AsyncMock(side_effect=RuntimeError("DB down"))

        agent, provider = self._make_agent(conv_store)

        from breadmind.core.protocols import LLMResponse, TokenUsage
        provider.chat.return_value = LLMResponse(
            content="response despite error",
            tool_calls=[],
            usage=TokenUsage(input_tokens=10, output_tokens=5),
            stop_reason="end_turn",
        )

        ctx = AgentContext(user="alice", channel="web", session_id="sess-1")
        resp = await agent.handle_message("hello", ctx)
        assert resp.content == "response despite error"
