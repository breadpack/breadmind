from unittest.mock import AsyncMock
import pytest
from breadmind.memory.episodic_recorder import LLMJsonAdapter


@pytest.mark.asyncio
async def test_parses_strict_json():
    base = AsyncMock()
    base.complete.return_value = '{"summary":"ok","keywords":["a"],"outcome":"success","should_record":true}'
    adapter = LLMJsonAdapter(base)
    out = await adapter.complete_json("prompt")
    assert out["summary"] == "ok"


@pytest.mark.asyncio
async def test_extracts_json_block_from_chatter():
    base = AsyncMock()
    base.complete.return_value = "여기 결과:\n```json\n{\"summary\":\"x\",\"keywords\":[],\"outcome\":\"neutral\",\"should_record\":true}\n```\n"
    adapter = LLMJsonAdapter(base)
    out = await adapter.complete_json("prompt")
    assert out["summary"] == "x"


@pytest.mark.asyncio
async def test_invalid_json_raises():
    base = AsyncMock()
    base.complete.return_value = "not json at all"
    adapter = LLMJsonAdapter(base)
    with pytest.raises(ValueError):
        await adapter.complete_json("prompt")
