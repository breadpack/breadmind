"""BuiltinMessageAdapter and message_search tool tests."""
from unittest.mock import AsyncMock, MagicMock
import pytest


@pytest.fixture
def mock_db():
    db = AsyncMock()
    conn = AsyncMock()

    class AcquireCM:
        async def __aenter__(self):
            return conn
        async def __aexit__(self, *args):
            pass

    db.acquire = MagicMock(return_value=AcquireCM())
    return db, conn


@pytest.mark.asyncio
async def test_list_messages_empty(mock_db):
    from breadmind.personal.adapters.builtin_message import BuiltinMessageAdapter
    db, conn = mock_db
    conn.fetch.return_value = []
    adapter = BuiltinMessageAdapter(db)
    messages = await adapter.list_items(filters={"user_id": "alice", "query": "hello"})
    assert messages == []


@pytest.mark.asyncio
async def test_list_messages_with_results(mock_db):
    from breadmind.personal.adapters.builtin_message import BuiltinMessageAdapter
    db, conn = mock_db
    conn.fetch.return_value = [
        {"session_id": "s1", "user_id": "alice", "channel": "web",
         "msg": {"role": "user", "content": "hello world"}},
        {"session_id": "s1", "user_id": "alice", "channel": "web",
         "msg": {"role": "assistant", "content": "hello there"}},
    ]
    adapter = BuiltinMessageAdapter(db)
    messages = await adapter.list_items(filters={"user_id": "alice", "query": "hello"})
    assert len(messages) == 2


@pytest.mark.asyncio
async def test_list_messages_filters_by_query(mock_db):
    from breadmind.personal.adapters.builtin_message import BuiltinMessageAdapter
    db, conn = mock_db
    conn.fetch.return_value = [
        {"session_id": "s1", "user_id": "alice", "channel": "web",
         "msg": {"role": "user", "content": "deploy to production"}},
        {"session_id": "s1", "user_id": "alice", "channel": "web",
         "msg": {"role": "user", "content": "hello world"}},
    ]
    adapter = BuiltinMessageAdapter(db)
    messages = await adapter.list_items(filters={"user_id": "alice", "query": "deploy"})
    assert len(messages) == 1
    assert "deploy" in messages[0].content


@pytest.mark.asyncio
async def test_skips_system_messages(mock_db):
    from breadmind.personal.adapters.builtin_message import BuiltinMessageAdapter
    db, conn = mock_db
    conn.fetch.return_value = [
        {"session_id": "s1", "user_id": "alice", "channel": "web",
         "msg": {"role": "system", "content": "system prompt"}},
    ]
    adapter = BuiltinMessageAdapter(db)
    messages = await adapter.list_items(filters={"user_id": "alice"})
    assert messages == []


@pytest.mark.asyncio
async def test_message_search_tool():
    from breadmind.personal.tools import message_search
    from breadmind.personal.adapters.base import AdapterRegistry
    from breadmind.personal.models import Message

    registry = AdapterRegistry()
    adapter = AsyncMock()
    adapter.domain = "message"
    adapter.source = "builtin"
    adapter.list_items = AsyncMock(return_value=[
        Message(id="m1", content="서버 배포 완료", sender="user", channel="web", platform="web")
    ])
    registry.register(adapter)

    result = await message_search(query="배포", registry=registry, user_id="alice")
    assert "배포" in result
