"""ClaudeAdapter prompt caching 최적화 테스트."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from breadmind.core.protocols import Message, PromptBlock, TokenUsage
from breadmind.plugins.builtin.providers.claude_adapter import ClaudeAdapter


@pytest.fixture
def adapter():
    return ClaudeAdapter(api_key="test-key", model="claude-sonnet-4-6")


class TestBlockSorting:
    """cacheable 블록이 앞에 정렬되는지 검증."""

    def test_cacheable_blocks_sorted_first(self, adapter):
        blocks = [
            PromptBlock(section="dynamic", content="dynamic content", cacheable=False, priority=5),
            PromptBlock(section="laws", content="iron laws", cacheable=True, priority=0),
            PromptBlock(section="persona", content="persona info", cacheable=True, priority=3),
            PromptBlock(section="env", content="env info", cacheable=False, priority=1),
        ]
        sorted_blocks = adapter._sort_blocks_for_cache(blocks)
        # cacheable이 앞에, priority 오름차순
        assert sorted_blocks[0].section == "laws"
        assert sorted_blocks[0].cacheable is True
        assert sorted_blocks[1].section == "persona"
        assert sorted_blocks[1].cacheable is True
        assert sorted_blocks[2].section == "env"
        assert sorted_blocks[2].cacheable is False
        assert sorted_blocks[3].section == "dynamic"
        assert sorted_blocks[3].cacheable is False

    def test_empty_blocks(self, adapter):
        assert adapter._sort_blocks_for_cache([]) == []

    def test_all_cacheable_sorted_by_priority(self, adapter):
        blocks = [
            PromptBlock(section="b", content="b", cacheable=True, priority=5),
            PromptBlock(section="a", content="a", cacheable=True, priority=1),
        ]
        sorted_blocks = adapter._sort_blocks_for_cache(blocks)
        assert sorted_blocks[0].section == "a"
        assert sorted_blocks[1].section == "b"


class TestCacheControlMarking:
    """cache_control이 올바르게 마킹되는지 검증."""

    def test_cacheable_block_gets_cache_control(self, adapter):
        blocks = [
            PromptBlock(section="laws", content="Never guess.", cacheable=True, priority=0,
                        provider_hints={"claude": {"scope": "global"}}),
        ]
        result = adapter.transform_system_prompt(blocks)
        assert len(result) == 1
        assert result[0]["cache_control"] == {"type": "ephemeral", "scope": "global"}

    def test_non_cacheable_block_no_cache_control(self, adapter):
        blocks = [
            PromptBlock(section="env", content="OS: Linux", cacheable=False, priority=5),
        ]
        result = adapter.transform_system_prompt(blocks)
        assert "cache_control" not in result[0]

    def test_default_scope_is_org(self, adapter):
        blocks = [
            PromptBlock(section="laws", content="content", cacheable=True, priority=0),
        ]
        result = adapter.transform_system_prompt(blocks)
        assert result[0]["cache_control"]["scope"] == "org"

    def test_tool_cache_control_on_last_tool(self, adapter):
        tools = [
            {"name": "tool_a", "description": "A", "input_schema": {}},
            {"name": "tool_b", "description": "B", "input_schema": {}},
        ]
        result = adapter._apply_tool_cache_control(tools)
        assert "cache_control" not in result[0]
        assert result[-1]["cache_control"] == {"type": "ephemeral"}
        # 원본 변경 없음
        assert "cache_control" not in tools[-1]

    def test_tool_cache_control_single_tool(self, adapter):
        tools = [{"name": "tool_a", "description": "A", "input_schema": {}}]
        result = adapter._apply_tool_cache_control(tools)
        assert result[0]["cache_control"] == {"type": "ephemeral"}

    def test_tool_cache_control_empty_list(self, adapter):
        assert adapter._apply_tool_cache_control([]) == []


class TestTokenUsageCache:
    """TokenUsage에 캐시 필드가 포함되는지 검증."""

    def test_cache_fields_default_zero(self):
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        assert usage.cache_creation_input_tokens == 0
        assert usage.cache_read_input_tokens == 0

    def test_total_tokens_includes_cache(self):
        usage = TokenUsage(
            input_tokens=100, output_tokens=50,
            cache_creation_input_tokens=200, cache_read_input_tokens=300,
        )
        assert usage.total_tokens == 650

    def test_cache_fields_explicit(self):
        usage = TokenUsage(
            input_tokens=10, output_tokens=20,
            cache_creation_input_tokens=30, cache_read_input_tokens=40,
        )
        assert usage.cache_creation_input_tokens == 30
        assert usage.cache_read_input_tokens == 40


class TestChatCacheIntegration:
    """chat() 메서드에서 캐시가 올바르게 동작하는지 검증."""

    @pytest.fixture
    def adapter_with_blocks(self):
        a = ClaudeAdapter(api_key="test-key", model="claude-sonnet-4-6")
        a.set_system_blocks([
            PromptBlock(section="laws", content="Never guess.", cacheable=True, priority=0),
            PromptBlock(section="env", content="OS: Linux", cacheable=False, priority=5),
        ])
        return a

    async def test_chat_uses_block_array_when_blocks_set(self, adapter_with_blocks):
        mock_usage = MagicMock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 50
        mock_usage.cache_creation_input_tokens = 200
        mock_usage.cache_read_input_tokens = 0

        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Hello"

        mock_response = MagicMock()
        mock_response.content = [mock_text_block]
        mock_response.usage = mock_usage
        mock_response.stop_reason = "end_turn"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        adapter_with_blocks._client = mock_client

        messages = [
            Message(role="system", content="Never guess.\n\nOS: Linux"),
            Message(role="user", content="hi"),
        ]
        result = await adapter_with_blocks.chat(messages)

        call_kwargs = mock_client.messages.create.call_args[1]
        # system이 블록 배열로 전달되었는지 확인
        assert isinstance(call_kwargs["system"], list)
        # cacheable 블록이 앞에 위치
        assert call_kwargs["system"][0]["cache_control"]["type"] == "ephemeral"
        assert "cache_control" not in call_kwargs["system"][1]
        # 캐시 토큰 파싱
        assert result.usage.cache_creation_input_tokens == 200
        assert result.usage.cache_read_input_tokens == 0

    async def test_chat_falls_back_to_string_without_blocks(self, adapter):
        mock_usage = MagicMock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 50
        mock_usage.cache_creation_input_tokens = None
        mock_usage.cache_read_input_tokens = None

        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Hello"

        mock_response = MagicMock()
        mock_response.content = [mock_text_block]
        mock_response.usage = mock_usage
        mock_response.stop_reason = "end_turn"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        adapter._client = mock_client

        messages = [
            Message(role="system", content="prompt"),
            Message(role="user", content="hi"),
        ]
        result = await adapter.chat(messages)

        call_kwargs = mock_client.messages.create.call_args[1]
        # blocks가 없으면 string으로 전달
        assert isinstance(call_kwargs["system"], str)
        # None은 0으로 처리
        assert result.usage.cache_creation_input_tokens == 0
        assert result.usage.cache_read_input_tokens == 0

    async def test_chat_applies_tool_cache_control(self, adapter_with_blocks):
        mock_usage = MagicMock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 50
        mock_usage.cache_creation_input_tokens = 0
        mock_usage.cache_read_input_tokens = 150

        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Hello"

        mock_response = MagicMock()
        mock_response.content = [mock_text_block]
        mock_response.usage = mock_usage
        mock_response.stop_reason = "end_turn"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        adapter_with_blocks._client = mock_client

        tools = [
            {"name": "shell", "description": "run shell", "input_schema": {}},
            {"name": "read", "description": "read file", "input_schema": {}},
        ]
        messages = [
            Message(role="system", content="prompt"),
            Message(role="user", content="hi"),
        ]
        await adapter_with_blocks.chat(messages, tools=tools)

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["tools"][-1]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in call_kwargs["tools"][0]
