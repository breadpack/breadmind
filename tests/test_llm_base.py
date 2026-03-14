from breadmind.llm.base import (
    LLMResponse, ToolCall, TokenUsage, LLMMessage
)


def test_llm_response_with_text():
    resp = LLMResponse(
        content="Hello",
        tool_calls=[],
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )
    assert resp.content == "Hello"
    assert resp.has_tool_calls is False


def test_llm_response_with_tool_call():
    tc = ToolCall(
        id="tc_1",
        name="k8s_list_pods",
        arguments={"namespace": "default"},
    )
    resp = LLMResponse(
        content=None,
        tool_calls=[tc],
        usage=TokenUsage(input_tokens=10, output_tokens=20),
        stop_reason="tool_use",
    )
    assert resp.has_tool_calls is True
    assert resp.tool_calls[0].name == "k8s_list_pods"


def test_llm_message_roles():
    msg = LLMMessage(role="user", content="hello")
    assert msg.role == "user"
