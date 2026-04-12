"""v2 프로토콜 타입 테스트."""
from breadmind.core.protocols.provider import Message, LLMResponse, ToolCallRequest, TokenUsage
from breadmind.core.protocols.prompt import PromptBlock, PromptContext, CompactResult
from breadmind.core.protocols.tool import ToolDefinition, ToolResult, ToolFilter, ToolSchema
from breadmind.core.protocols.memory import Episode, KGTriple
from breadmind.core.protocols.agent import AgentContext, AgentResponse
from breadmind.core.protocols.runtime import UserInput, AgentOutput, Progress


# --- Provider types ---

def test_message_creation():
    msg = Message(role="user", content="hello")
    assert msg.role == "user"
    assert msg.content == "hello"
    assert msg.tool_calls == []
    assert msg.tool_call_id is None
    assert msg.is_meta is False

def test_message_system_role():
    msg = Message(role="system", content="prompt")
    assert msg.role == "system"

def test_llm_response_with_tool_calls():
    tc = ToolCallRequest(id="tc_1", name="shell_exec", arguments={"command": "ls"})
    resp = LLMResponse(content=None, tool_calls=[tc], usage=TokenUsage(input_tokens=10, output_tokens=5), stop_reason="tool_use")
    assert resp.has_tool_calls is True
    assert resp.tool_calls[0].name == "shell_exec"

def test_llm_response_text_only():
    resp = LLMResponse(content="hello", tool_calls=[], usage=TokenUsage(input_tokens=10, output_tokens=5), stop_reason="end_turn")
    assert resp.has_tool_calls is False

def test_token_usage_total():
    usage = TokenUsage(input_tokens=100, output_tokens=50)
    assert usage.total_tokens == 150


# --- Prompt types ---

def test_prompt_block_creation():
    block = PromptBlock(section="iron_laws", content="Never guess.", cacheable=True, priority=0)
    assert block.section == "iron_laws"
    assert block.cacheable is True
    assert block.provider_hints == {}

def test_prompt_block_with_hints():
    block = PromptBlock(section="identity", content="You are BreadMind.", cacheable=True, priority=1, provider_hints={"claude": {"scope": "global"}})
    assert block.provider_hints["claude"]["scope"] == "global"

def test_prompt_context_defaults():
    ctx = PromptContext()
    assert ctx.persona_name == "BreadMind"
    assert ctx.language == "ko"
    assert ctx.available_tools == []

def test_compact_result():
    boundary = Message(role="system", content="Summary.")
    preserved = [Message(role="user", content="latest")]
    result = CompactResult(boundary=boundary, preserved=preserved, tokens_saved=500)
    assert result.tokens_saved == 500


# --- Tool types ---

def test_tool_definition():
    td = ToolDefinition(name="shell_exec", description="Execute shell command", parameters={"type": "object"})
    assert td.name == "shell_exec"

def test_tool_result_success():
    result = ToolResult(success=True, output="file.txt")
    assert result.success is True

def test_tool_result_failure():
    result = ToolResult(success=False, output="", error="Permission denied")
    assert result.error == "Permission denied"

def test_tool_filter_deferred():
    f = ToolFilter(use_deferred=True, always_include=["shell_exec"])
    assert f.use_deferred is True

def test_tool_schema_deferred():
    s = ToolSchema(name="k8s_pods_list", deferred=True)
    assert s.deferred is True
    assert s.definition is None


# --- Memory types ---

def test_episode_creation():
    ep = Episode(id="ep_1", content="User asked about pod crashes", keywords=["pod", "crash"], timestamp="2026-04-04T12:00:00Z")
    assert ep.id == "ep_1"
    assert "pod" in ep.keywords

def test_kg_triple():
    t = KGTriple(subject="pod-abc", predicate="runs_on", object="node-1")
    assert t.predicate == "runs_on"


# --- Agent types ---

def test_agent_context_defaults():
    ctx = AgentContext(user="admin", channel="cli", session_id="s1")
    assert ctx.depth == 0
    assert ctx.max_depth == 5
    assert ctx.parent_agent is None

def test_agent_context_nested():
    ctx = AgentContext(user="admin", channel="cli", session_id="s1", parent_agent="root", depth=2)
    assert ctx.depth == 2

def test_agent_response():
    resp = AgentResponse(content="Done.", tool_calls_count=3, tokens_used=150)
    assert resp.tool_calls_count == 3


# --- Runtime types ---

def test_user_input():
    inp = UserInput(text="hello")
    assert inp.user == "anonymous"
    assert inp.channel == "default"

def test_agent_output():
    out = AgentOutput(text="response")
    assert out.metadata == {}

def test_progress():
    p = Progress(status="thinking", detail="Processing...")
    assert p.status == "thinking"


# --- Cross-module import test ---

def test_protocols_package_import():
    from breadmind.core.protocols import Message, PromptBlock
    assert Message is not None
    assert PromptBlock is not None
