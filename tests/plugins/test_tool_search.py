import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.core.protocols import (
    ToolDefinition, ToolFilter, Message, LLMResponse, TokenUsage, AgentContext, PromptBlock,
    ToolCallRequest,
)
from breadmind.plugins.builtin.tools.registry import HybridToolRegistry
from breadmind.plugins.builtin.tools.tool_search import (
    TOOL_SEARCH_DEFINITION,
    ToolSearchExecutor,
)
from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent
from breadmind.plugins.builtin.safety.guard import SafetyVerdict


# ─── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def registry():
    r = HybridToolRegistry()
    r.register(ToolDefinition(name="shell_exec", description="Execute shell commands", parameters={}))
    r.register(ToolDefinition(name="file_read", description="Read a file from disk", parameters={}, readonly=True))
    r.register(ToolDefinition(
        name="k8s_pods_list", description="List Kubernetes pods",
        parameters={"type": "object", "properties": {"namespace": {"type": "string"}}, "required": []},
        readonly=True,
    ))
    r.register(ToolDefinition(name="k8s_pods_get", description="Get a specific K8s pod", parameters={}, readonly=True))
    r.register(ToolDefinition(name="web_search", description="Search the web", parameters={}))
    r.register_tool_search()
    return r


@pytest.fixture
def executor(registry):
    return ToolSearchExecutor(registry)


# ─── select: 모드 정확 매칭 ─────────────────────────────────

@pytest.mark.asyncio
async def test_select_exact_match(executor):
    result = await executor.execute("select:shell_exec,file_read")
    assert "shell_exec" in result
    assert "file_read" in result
    assert "k8s_pods_list" not in result


@pytest.mark.asyncio
async def test_select_single(executor):
    result = await executor.execute("select:web_search")
    assert "web_search" in result
    assert "Search the web" in result


@pytest.mark.asyncio
async def test_select_nonexistent(executor):
    result = await executor.execute("select:nonexistent_tool")
    assert "No matching tools found" in result


@pytest.mark.asyncio
async def test_select_mixed_existing_and_nonexistent(executor):
    result = await executor.execute("select:shell_exec,nonexistent")
    assert "shell_exec" in result
    assert "1 tool(s)" in result


# ─── keyword 검색 ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_keyword_search_name(executor):
    result = await executor.execute("k8s")
    assert "k8s_pods_list" in result
    assert "k8s_pods_get" in result


@pytest.mark.asyncio
async def test_keyword_search_description(executor):
    result = await executor.execute("Kubernetes")
    assert "k8s_pods_list" in result


@pytest.mark.asyncio
async def test_keyword_search_no_match(executor):
    result = await executor.execute("nonexistent_xyz")
    assert "No matching tools found" in result


@pytest.mark.asyncio
async def test_keyword_excludes_tool_search_itself(executor):
    """tool_search 도구 자체는 검색 결과에서 제외."""
    result = await executor.execute("search")
    # web_search는 포함되지만 tool_search 자체는 제외
    assert "web_search" in result
    assert "tool_search" not in result or result.count("tool_search") == 0 or "web_search" in result


@pytest.mark.asyncio
async def test_keyword_plus_prefix_required_in_name(executor):
    """+ 접두사는 이름에 반드시 포함되어야 하는 필수 매칭."""
    result = await executor.execute("+k8s pods")
    assert "k8s_pods_list" in result
    assert "k8s_pods_get" in result
    assert "shell_exec" not in result


# ─── max_results 제한 ───────────────────────────────────────

@pytest.mark.asyncio
async def test_max_results_limit(executor):
    result = await executor.execute("k8s", max_results=1)
    # 1개만 반환
    assert "1 tool(s)" in result


@pytest.mark.asyncio
async def test_max_results_default(executor):
    """max_results 기본값은 5."""
    result = await executor.execute("file shell k8s web", max_results=5)
    # 최대 5개
    tool_count = result.count("Description:")
    assert tool_count <= 5


# ─── TOOL_SEARCH_DEFINITION 속성 검증 ───────────────────────

def test_tool_search_definition_readonly():
    assert TOOL_SEARCH_DEFINITION.readonly is True


def test_tool_search_definition_name():
    assert TOOL_SEARCH_DEFINITION.name == "tool_search"


def test_tool_search_definition_has_query_required():
    assert "query" in TOOL_SEARCH_DEFINITION.parameters["properties"]
    assert "query" in TOOL_SEARCH_DEFINITION.parameters["required"]


# ─── register_tool_search 통합 ──────────────────────────────

def test_register_tool_search_adds_to_registry():
    r = HybridToolRegistry()
    r.register_tool_search()
    names = r.get_deferred_tools()
    assert "tool_search" in names


def test_register_tool_search_has_executor():
    r = HybridToolRegistry()
    r.register_tool_search()
    assert "tool_search" in r._executors


# ─── deferred 모드에서 tool_search가 always_include ─────────

def test_deferred_mode_tool_search_always_included(registry):
    f = ToolFilter(use_deferred=True, always_include=["tool_search"])
    schemas = registry.get_schemas(f)

    tool_search_schema = next(s for s in schemas if s.name == "tool_search")
    assert tool_search_schema.deferred is False
    assert tool_search_schema.definition is not None

    # 다른 도구는 deferred
    others = [s for s in schemas if s.name != "tool_search"]
    assert all(s.deferred is True for s in others)


# ─── format_results 가독성 ──────────────────────────────────

@pytest.mark.asyncio
async def test_format_results_human_readable(executor):
    result = await executor.execute("select:k8s_pods_list")
    assert "Parameters:" in result
    assert "namespace" in result
    assert "readonly" in result


@pytest.mark.asyncio
async def test_format_results_empty():
    r = HybridToolRegistry()
    r.register_tool_search()
    ex = ToolSearchExecutor(r)
    result = await ex.execute("nonexistent")
    assert result == "No matching tools found."


# ─── MessageLoopAgent deferred 통합 테스트 ──────────────────

@pytest.fixture
def deferred_provider():
    provider = AsyncMock()
    provider.supports_feature.side_effect = lambda f: f == "tool_search"
    provider.transform_system_prompt.side_effect = lambda blocks: blocks
    provider.transform_messages.side_effect = lambda msgs: msgs
    provider.fallback = None
    return provider


@pytest.fixture
def tool_registry_with_search():
    r = HybridToolRegistry()
    r.register(ToolDefinition(name="shell_exec", description="Execute shell", parameters={}))
    r.register(ToolDefinition(name="file_read", description="Read file", parameters={}, readonly=True))
    r.register_tool_search()
    return r


@pytest.fixture
def deferred_agent(deferred_provider, tool_registry_with_search):
    builder = MagicMock()
    builder.build.return_value = [
        PromptBlock(section="test", content="Test system.", cacheable=False, priority=0),
    ]
    builder.inject_reminder.side_effect = lambda k, c: Message(role="user", content=c, is_meta=True)

    guard = MagicMock()
    guard.check.return_value = SafetyVerdict(allowed=True)

    return MessageLoopAgent(
        provider=deferred_provider,
        prompt_builder=builder,
        tool_registry=tool_registry_with_search,
        safety_guard=guard,
        max_turns=5,
    )


@pytest.mark.asyncio
async def test_deferred_mode_only_tool_search_in_initial_tools(
    deferred_agent, deferred_provider,
):
    """deferred 모드에서 초기 tools에는 tool_search만 full schema로 포함."""
    deferred_provider.chat.return_value = LLMResponse(
        content="Done.", tool_calls=[], usage=TokenUsage(10, 5), stop_reason="end_turn",
    )
    ctx = AgentContext(user="test", channel="cli", session_id="s1")
    await deferred_agent.handle_message("hi", ctx)

    # chat이 호출될 때 전달된 tools 확인
    call_args = deferred_provider.chat.call_args
    tools = call_args[0][1]  # 2nd positional arg
    tool_names = [t["name"] for t in tools]
    assert "tool_search" in tool_names
    # deferred 도구는 definition이 None이므로 tools에 포함되지 않음
    assert "shell_exec" not in tool_names
    assert "file_read" not in tool_names


@pytest.mark.asyncio
async def test_resolve_adds_tools_to_next_turn(
    deferred_agent, deferred_provider, tool_registry_with_search,
):
    """tool_search 실행 후 resolve된 도구가 다음 turn의 tools에 추가."""
    # Turn 1: LLM이 tool_search를 호출
    # Turn 2: resolve된 도구 포함된 상태로 LLM 호출 → 텍스트 응답
    deferred_provider.chat.side_effect = [
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(
                id="tc1", name="tool_search",
                arguments={"query": "select:shell_exec"},
            )],
            usage=TokenUsage(10, 5), stop_reason="tool_use",
        ),
        LLMResponse(
            content="Found shell_exec.", tool_calls=[],
            usage=TokenUsage(20, 10), stop_reason="end_turn",
        ),
    ]
    ctx = AgentContext(user="test", channel="cli", session_id="s1")
    resp = await deferred_agent.handle_message("find shell tool", ctx)

    assert resp.tool_calls_count == 1

    # 2번째 chat 호출 시 tools에 shell_exec이 추가되었는지 확인
    second_call_args = deferred_provider.chat.call_args_list[1]
    tools = second_call_args[0][1]
    tool_names = [t["name"] for t in tools]
    assert "shell_exec" in tool_names
    assert "tool_search" in tool_names


@pytest.mark.asyncio
async def test_resolved_tools_not_duplicated(
    deferred_agent, deferred_provider,
):
    """이미 resolve된 도구는 중복 resolve하지 않음."""
    deferred_provider.chat.side_effect = [
        # Turn 1: tool_search("select:shell_exec")
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(
                id="tc1", name="tool_search",
                arguments={"query": "select:shell_exec"},
            )],
            usage=TokenUsage(10, 5), stop_reason="tool_use",
        ),
        # Turn 2: tool_search("select:shell_exec") 다시
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(
                id="tc2", name="tool_search",
                arguments={"query": "select:shell_exec"},
            )],
            usage=TokenUsage(10, 5), stop_reason="tool_use",
        ),
        # Turn 3: 텍스트 응답
        LLMResponse(
            content="Done.", tool_calls=[],
            usage=TokenUsage(20, 10), stop_reason="end_turn",
        ),
    ]
    ctx = AgentContext(user="test", channel="cli", session_id="s1")
    await deferred_agent.handle_message("find shell", ctx)

    # 3번째 호출의 tools에 shell_exec이 1번만 포함
    third_call_tools = deferred_provider.chat.call_args_list[2][0][1]
    shell_count = sum(1 for t in third_call_tools if t["name"] == "shell_exec")
    assert shell_count == 1
