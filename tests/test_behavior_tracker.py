import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.config import build_system_prompt, DEFAULT_PERSONA, _PROACTIVE_BEHAVIOR_PROMPT
from breadmind.core.behavior_tracker import BehaviorTracker
from breadmind.llm.base import LLMMessage, LLMResponse, ToolCall, TokenUsage


# --- Task 1 tests: build_system_prompt ---

def test_build_system_prompt_default_behavior():
    result = build_system_prompt(DEFAULT_PERSONA)
    assert _PROACTIVE_BEHAVIOR_PROMPT in result


def test_build_system_prompt_custom_behavior():
    custom = "Custom behavior rules here."
    result = build_system_prompt(DEFAULT_PERSONA, behavior_prompt=custom)
    assert custom in result
    assert _PROACTIVE_BEHAVIOR_PROMPT not in result


def test_build_system_prompt_none_behavior_uses_default():
    result = build_system_prompt(DEFAULT_PERSONA, behavior_prompt=None)
    assert _PROACTIVE_BEHAVIOR_PROMPT in result


# --- Helpers ---

def _make_messages_with_tools():
    return [
        LLMMessage(role="system", content="system prompt"),
        LLMMessage(role="user", content="서버 상태 확인해줘"),
        LLMMessage(
            role="assistant", content=None,
            tool_calls=[ToolCall(id="tc1", name="shell_exec", arguments={"command": "uptime"})],
        ),
        LLMMessage(role="tool", content="[success=True] up 30 days", tool_call_id="tc1", name="shell_exec"),
        LLMMessage(role="assistant", content="서버가 30일째 가동 중입니다."),
        LLMMessage(role="user", content="고마워"),
    ]


def _make_messages_text_only():
    return [
        LLMMessage(role="system", content="system prompt"),
        LLMMessage(role="user", content="디스크 용량 알려줘"),
        LLMMessage(role="assistant", content="df -h 명령어를 사용하면 확인할 수 있습니다."),
        LLMMessage(role="user", content="직접 해줘"),
    ]


def _make_messages_too_short():
    return [
        LLMMessage(role="system", content="system prompt"),
        LLMMessage(role="user", content="안녕"),
        LLMMessage(role="assistant", content="안녕하세요!"),
    ]


def _make_tracker(llm_response_content: str) -> tuple[BehaviorTracker, MagicMock, MagicMock]:
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=LLMResponse(
        content=llm_response_content,
        tool_calls=[],
        usage=TokenUsage(input_tokens=100, output_tokens=50),
        stop_reason="end_turn",
    ))
    current_prompt = "Current behavior prompt."
    set_prompt = MagicMock()
    add_notification = MagicMock()
    tracker = BehaviorTracker(
        provider=provider,
        get_behavior_prompt=lambda: current_prompt,
        set_behavior_prompt=set_prompt,
        add_notification=add_notification,
        db=None,
    )
    return tracker, set_prompt, add_notification


# --- Task 2 tests: metrics extraction ---

def test_extract_metrics_with_tools():
    tracker = BehaviorTracker.__new__(BehaviorTracker)
    metrics = tracker._extract_metrics(_make_messages_with_tools())
    assert metrics["tool_call_count"] == 1
    assert metrics["tool_success_count"] == 1
    assert metrics["tool_failure_count"] == 0
    assert metrics["text_only_response"] is False
    assert len(metrics["tool_calls"]) == 1
    assert metrics["tool_calls"][0]["name"] == "shell_exec"
    assert metrics["positive_feedback"] is True


def test_extract_metrics_text_only():
    tracker = BehaviorTracker.__new__(BehaviorTracker)
    metrics = tracker._extract_metrics(_make_messages_text_only())
    assert metrics["tool_call_count"] == 0
    assert metrics["text_only_response"] is True
    assert metrics["negative_feedback"] is True


def test_should_analyze_too_short():
    tracker = BehaviorTracker.__new__(BehaviorTracker)
    assert tracker._should_analyze(_make_messages_too_short()) is False


def test_should_analyze_sufficient():
    tracker = BehaviorTracker.__new__(BehaviorTracker)
    assert tracker._should_analyze(_make_messages_with_tools()) is True


# --- Task 3 tests: analyze ---

@pytest.mark.asyncio
async def test_analyze_no_change():
    tracker, set_prompt, add_notification = _make_tracker("NO_CHANGE")
    result = await tracker.analyze("s1", _make_messages_with_tools())
    assert result is None
    set_prompt.assert_not_called()
    add_notification.assert_not_called()


@pytest.mark.asyncio
async def test_analyze_with_improvement():
    response = "REASON: 도구 사용 패턴 개선\n---\nImproved behavior prompt."
    tracker, set_prompt, add_notification = _make_tracker(response)
    result = await tracker.analyze("s1", _make_messages_with_tools())
    assert result is not None
    assert result["reason"] == "도구 사용 패턴 개선"
    set_prompt.assert_called_once_with("Improved behavior prompt.")
    add_notification.assert_called_once()


@pytest.mark.asyncio
async def test_analyze_too_long_prompt_rejected():
    response = "REASON: test\n---\n" + "x" * 2001
    tracker, set_prompt, add_notification = _make_tracker(response)
    result = await tracker.analyze("s1", _make_messages_with_tools())
    assert result is None
    set_prompt.assert_not_called()


@pytest.mark.asyncio
async def test_analyze_skips_short_conversation():
    tracker, set_prompt, _ = _make_tracker("NO_CHANGE")
    result = await tracker.analyze("s1", _make_messages_too_short())
    assert result is None
    set_prompt.assert_not_called()


@pytest.mark.asyncio
async def test_analyze_db_persistence():
    response = "REASON: persist test\n---\nNew prompt."
    tracker, set_prompt, _ = _make_tracker(response)
    tracker._db = AsyncMock()
    tracker._db.set_setting = AsyncMock()
    await tracker.analyze("s1", _make_messages_with_tools())
    tracker._db.set_setting.assert_called_once()
    call_args = tracker._db.set_setting.call_args
    assert call_args[0][0] == "behavior_prompt"
    assert call_args[0][1]["prompt"] == "New prompt."


# --- Task 4-6 tests: CoreAgent integration ---

from breadmind.core.agent import CoreAgent
from breadmind.core.safety import SafetyGuard
from breadmind.tools.registry import ToolRegistry


def test_agent_behavior_prompt_getter_setter():
    provider = AsyncMock()
    agent = CoreAgent(
        provider=provider,
        tool_registry=ToolRegistry(),
        safety_guard=SafetyGuard(),
        behavior_prompt="initial behavior",
    )
    assert agent.get_behavior_prompt() == "initial behavior"
    agent.set_behavior_prompt("updated behavior")
    assert agent.get_behavior_prompt() == "updated behavior"
    assert "updated behavior" in agent._system_prompt


@pytest.mark.asyncio
async def test_agent_notifications_prepended():
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=LLMResponse(
        content="response", tool_calls=[],
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    ))
    agent = CoreAgent(
        provider=provider,
        tool_registry=ToolRegistry(),
        safety_guard=SafetyGuard(),
    )
    agent.add_notification("test notification")
    result = await agent.handle_message("hi", "user1", "test")
    assert "test notification" in result
    assert "response" in result
    # Second call should not have notification
    result2 = await agent.handle_message("hi again", "user1", "test")
    assert "test notification" not in result2


def test_set_persona_preserves_behavior_prompt():
    provider = AsyncMock()
    agent = CoreAgent(
        provider=provider,
        tool_registry=ToolRegistry(),
        safety_guard=SafetyGuard(),
        behavior_prompt="my custom rules",
    )
    agent.set_persona({"name": "TestBot", "language": "en", "preset": "friendly",
                        "system_prompt": "You are TestBot."})
    assert "my custom rules" in agent._system_prompt
    assert "TestBot" in agent._system_prompt
