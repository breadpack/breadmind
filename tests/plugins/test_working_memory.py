import pytest
from unittest.mock import AsyncMock
from breadmind.core.protocols import Message
from breadmind.plugins.v2_builtin.memory.working_memory import WorkingMemory


@pytest.mark.asyncio
async def test_put_and_get():
    wm = WorkingMemory()
    msgs = [Message(role="user", content="hello"), Message(role="assistant", content="hi")]
    await wm.working_put("s1", msgs)
    result = await wm.working_get("s1")
    assert len(result) == 2
    assert result[0].content == "hello"


@pytest.mark.asyncio
async def test_get_empty_session():
    wm = WorkingMemory()
    result = await wm.working_get("nonexistent")
    assert result == []


@pytest.mark.asyncio
async def test_truncation_on_max():
    wm = WorkingMemory(max_messages=5, compress_threshold=100)
    msgs = [Message(role="user", content=f"msg-{i}") for i in range(10)]
    await wm.working_put("s1", msgs)
    result = await wm.working_get("s1")
    assert len(result) == 5
    assert result[0].content == "msg-5"


@pytest.mark.asyncio
async def test_compress_with_compressor():
    compressor = AsyncMock()
    compressor.summarize = AsyncMock(return_value="Summary of old messages")
    wm = WorkingMemory(compress_threshold=5, keep_recent=3, compressor=compressor)
    msgs = [Message(role="user", content=f"msg-{i}") for i in range(8)]
    await wm.working_put("s1", msgs)
    result = await wm.working_get("s1")
    assert any("Summary" in (m.content or "") for m in result)
    assert len(result) == 4  # 1 summary + 3 recent


@pytest.mark.asyncio
async def test_clear_session():
    wm = WorkingMemory()
    await wm.working_put("s1", [Message(role="user", content="hi")])
    wm.clear_session("s1")
    result = await wm.working_get("s1")
    assert result == []


@pytest.mark.asyncio
async def test_get_session_ids():
    wm = WorkingMemory()
    await wm.working_put("s1", [Message(role="user", content="a")])
    await wm.working_put("s2", [Message(role="user", content="b")])
    ids = wm.get_session_ids()
    assert "s1" in ids
    assert "s2" in ids
