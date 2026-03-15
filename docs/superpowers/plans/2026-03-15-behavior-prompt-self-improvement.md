# Behavior Prompt Self-Improvement Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 매 대화 종료 후 전체 대화 컨텍스트를 분석하여 행동 프롬프트를 자동 개선하는 BehaviorTracker 구현

**Architecture:** BehaviorTracker가 대화 메시지에서 메트릭을 추출하고, LLM에 현재 프롬프트 + 메트릭을 전달하여 개선안을 생성. CoreAgent가 handle_message 종료 시 fire-and-forget으로 분석 호출. 개선 결과는 DB에 저장하고 다음 응답에 알림 포함.

**Tech Stack:** Python 3.12+, asyncio, pytest

---

## File Structure

| 파일 | 역할 |
|------|------|
| `src/breadmind/core/behavior_tracker.py` | **신규** — BehaviorTracker 클래스 (메트릭 추출, LLM 분석, 프롬프트 업데이트) |
| `src/breadmind/core/agent.py` | **수정** — behavior_prompt 필드, notifications 큐, _safe_analyze 호출 |
| `src/breadmind/config.py` | **수정** — build_system_prompt에 behavior_prompt 파라미터 추가 |
| `src/breadmind/main.py` | **수정** — BehaviorTracker 생성, DB에서 behavior_prompt 로드 |
| `tests/test_behavior_tracker.py` | **신규** — BehaviorTracker 단위 테스트 |

---

## Chunk 1: BehaviorTracker 핵심 로직

### Task 1: config.py — build_system_prompt에 behavior_prompt 파라미터 추가

**Files:**
- Modify: `src/breadmind/config.py:152-172`
- Test: `tests/test_behavior_tracker.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_behavior_tracker.py
import pytest
from breadmind.config import build_system_prompt, DEFAULT_PERSONA, _PROACTIVE_BEHAVIOR_PROMPT


def test_build_system_prompt_default_behavior():
    """기본 호출 시 _PROACTIVE_BEHAVIOR_PROMPT가 포함된다."""
    result = build_system_prompt(DEFAULT_PERSONA)
    assert _PROACTIVE_BEHAVIOR_PROMPT in result


def test_build_system_prompt_custom_behavior():
    """behavior_prompt를 전달하면 기본값 대신 사용된다."""
    custom = "Custom behavior rules here."
    result = build_system_prompt(DEFAULT_PERSONA, behavior_prompt=custom)
    assert custom in result
    assert _PROACTIVE_BEHAVIOR_PROMPT not in result


def test_build_system_prompt_none_behavior_uses_default():
    """behavior_prompt=None이면 기본값을 사용한다."""
    result = build_system_prompt(DEFAULT_PERSONA, behavior_prompt=None)
    assert _PROACTIVE_BEHAVIOR_PROMPT in result
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_behavior_tracker.py::test_build_system_prompt_custom_behavior -v`
Expected: FAIL — `build_system_prompt()` got unexpected keyword argument 'behavior_prompt'

- [ ] **Step 3: build_system_prompt 수정**

`src/breadmind/config.py`의 `build_system_prompt` 함수 시그니처에 `behavior_prompt: str | None = None` 추가, `parts.append`에서 `behavior_prompt or _PROACTIVE_BEHAVIOR_PROMPT` 사용:

```python
def build_system_prompt(persona: dict, behavior_prompt: str | None = None) -> str:
    """Build full system prompt from persona config."""
    parts = [persona.get("system_prompt", DEFAULT_PERSONA["system_prompt"])]

    name = persona.get("name", "BreadMind")
    lang = persona.get("language", "ko")
    specialties = persona.get("specialties", [])

    if lang != "en":
        lang_names = {"ko": "Korean", "ja": "Japanese", "zh": "Chinese", "es": "Spanish", "de": "German", "fr": "French"}
        parts.append(f"Always respond in {lang_names.get(lang, lang)}.")

    if specialties:
        parts.append(f"Your primary expertise areas: {', '.join(specialties)}.")

    parts.append(f"Your name is {name}.")

    # Append proactive execution behavior
    parts.append(behavior_prompt or _PROACTIVE_BEHAVIOR_PROMPT)

    return "\n\n".join(parts)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_behavior_tracker.py -v`
Expected: 3 PASSED

- [ ] **Step 5: 커밋**

```bash
git add src/breadmind/config.py tests/test_behavior_tracker.py
git commit -m "feat: add behavior_prompt parameter to build_system_prompt"
```

---

### Task 2: BehaviorTracker — 메트릭 추출

**Files:**
- Create: `src/breadmind/core/behavior_tracker.py`
- Test: `tests/test_behavior_tracker.py`

- [ ] **Step 1: 메트릭 추출 테스트 작성**

```python
# tests/test_behavior_tracker.py에 추가
from breadmind.core.behavior_tracker import BehaviorTracker
from breadmind.llm.base import LLMMessage, ToolCall


def _make_messages_with_tools():
    """도구를 사용한 대화 메시지 리스트."""
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
    """도구 없이 텍스트만 응답한 대화."""
    return [
        LLMMessage(role="system", content="system prompt"),
        LLMMessage(role="user", content="디스크 용량 알려줘"),
        LLMMessage(role="assistant", content="df -h 명령어를 사용하면 확인할 수 있습니다."),
        LLMMessage(role="user", content="직접 해줘"),
    ]


def _make_messages_too_short():
    """분석 대상이 아닌 짧은 대화."""
    return [
        LLMMessage(role="system", content="system prompt"),
        LLMMessage(role="user", content="안녕"),
        LLMMessage(role="assistant", content="안녕하세요!"),
    ]


def test_extract_metrics_with_tools():
    tracker = BehaviorTracker.__new__(BehaviorTracker)
    metrics = BehaviorTracker._extract_metrics(tracker, _make_messages_with_tools())
    assert metrics["tool_call_count"] == 1
    assert metrics["tool_success_count"] == 1
    assert metrics["tool_failure_count"] == 0
    assert metrics["text_only_response"] is False
    assert len(metrics["tool_calls"]) == 1
    assert metrics["tool_calls"][0]["name"] == "shell_exec"
    assert metrics["positive_feedback"] is True


def test_extract_metrics_text_only():
    tracker = BehaviorTracker.__new__(BehaviorTracker)
    metrics = BehaviorTracker._extract_metrics(tracker, _make_messages_text_only())
    assert metrics["tool_call_count"] == 0
    assert metrics["text_only_response"] is True
    assert metrics["negative_feedback"] is True


def test_should_analyze_too_short():
    tracker = BehaviorTracker.__new__(BehaviorTracker)
    assert BehaviorTracker._should_analyze(tracker, _make_messages_too_short()) is False


def test_should_analyze_sufficient():
    tracker = BehaviorTracker.__new__(BehaviorTracker)
    assert BehaviorTracker._should_analyze(tracker, _make_messages_with_tools()) is True
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_behavior_tracker.py::test_extract_metrics_with_tools -v`
Expected: FAIL — ModuleNotFoundError: No module named 'breadmind.core.behavior_tracker'

- [ ] **Step 3: BehaviorTracker 메트릭 추출 구현**

```python
# src/breadmind/core/behavior_tracker.py
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from breadmind.llm.base import LLMMessage, LLMProvider

if TYPE_CHECKING:
    from breadmind.storage.database import Database

logger = logging.getLogger("breadmind.behavior")

_MAX_PROMPT_LENGTH = 2000

_NEGATIVE_PATTERNS = [
    "그게 아니라", "아닌데", "왜 안 해", "직접 해", "도구를 써",
    "실행해줘", "확인해봐", "안 되잖아", "다시 해", "틀렸",
]
_POSITIVE_PATTERNS = [
    "고마워", "잘했어", "좋아", "완벽", "정확해", "감사",
]


class BehaviorTracker:
    def __init__(
        self,
        provider: LLMProvider,
        get_behavior_prompt: Callable[[], str],
        set_behavior_prompt: Callable[[str], None],
        add_notification: Callable[[str], None],
        db: Database | None = None,
    ):
        self._provider = provider
        self._get_behavior_prompt = get_behavior_prompt
        self._set_behavior_prompt = set_behavior_prompt
        self._add_notification = add_notification
        self._db = db
        self._lock = asyncio.Lock()

    def _should_analyze(self, messages: list[LLMMessage]) -> bool:
        """분석할 만한 충분한 대화인지 판단."""
        user_msgs = [m for m in messages if m.role == "user"]
        total = len(messages)
        return len(user_msgs) >= 2 and total >= 4

    def _extract_metrics(self, messages: list[LLMMessage]) -> dict[str, Any]:
        """대화 메시지에서 구조화된 메트릭 추출."""
        tool_calls: list[dict] = []
        tool_success = 0
        tool_failure = 0
        text_only = True
        user_messages: list[str] = []
        has_negative = False
        has_positive = False

        for msg in messages:
            if msg.role == "user" and msg.content:
                user_messages.append(msg.content[:200])
                content_lower = msg.content.lower()
                if any(p in content_lower for p in _NEGATIVE_PATTERNS):
                    has_negative = True
                if any(p in content_lower for p in _POSITIVE_PATTERNS):
                    has_positive = True

            if msg.role == "assistant" and msg.tool_calls:
                text_only = False
                for tc in msg.tool_calls:
                    tool_calls.append({"name": tc.name, "args_keys": list(tc.arguments.keys())})

            if msg.role == "tool" and msg.content:
                if "[success=True]" in msg.content:
                    tool_success += 1
                elif "[success=False]" in msg.content:
                    tool_failure += 1

        return {
            "tool_call_count": len(tool_calls),
            "tool_success_count": tool_success,
            "tool_failure_count": tool_failure,
            "text_only_response": text_only,
            "tool_calls": tool_calls,
            "user_messages": user_messages[:10],
            "negative_feedback": has_negative,
            "positive_feedback": has_positive,
        }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_behavior_tracker.py -v`
Expected: 7 PASSED

- [ ] **Step 5: 커밋**

```bash
git add src/breadmind/core/behavior_tracker.py tests/test_behavior_tracker.py
git commit -m "feat: BehaviorTracker with metrics extraction"
```

---

### Task 3: BehaviorTracker — LLM 분석 및 프롬프트 업데이트

**Files:**
- Modify: `src/breadmind/core/behavior_tracker.py`
- Test: `tests/test_behavior_tracker.py`

- [ ] **Step 1: analyze 테스트 작성**

```python
# tests/test_behavior_tracker.py에 추가
import asyncio
from unittest.mock import AsyncMock, MagicMock
from breadmind.llm.base import LLMResponse, TokenUsage


def _make_tracker(llm_response_content: str) -> tuple[BehaviorTracker, MagicMock, MagicMock]:
    """테스트용 BehaviorTracker 생성."""
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


@pytest.mark.asyncio
async def test_analyze_no_change():
    """LLM이 NO_CHANGE를 반환하면 프롬프트를 변경하지 않는다."""
    tracker, set_prompt, add_notification = _make_tracker("NO_CHANGE")
    result = await tracker.analyze("s1", _make_messages_with_tools())
    assert result is None
    set_prompt.assert_not_called()
    add_notification.assert_not_called()


@pytest.mark.asyncio
async def test_analyze_with_improvement():
    """LLM이 개선안을 반환하면 프롬프트를 업데이트한다."""
    response = "REASON: 도구 사용 패턴 개선\n---\nImproved behavior prompt."
    tracker, set_prompt, add_notification = _make_tracker(response)
    result = await tracker.analyze("s1", _make_messages_with_tools())
    assert result is not None
    assert result["reason"] == "도구 사용 패턴 개선"
    set_prompt.assert_called_once_with("Improved behavior prompt.")
    add_notification.assert_called_once()


@pytest.mark.asyncio
async def test_analyze_too_long_prompt_rejected():
    """2000자 초과 프롬프트는 적용하지 않는다."""
    response = "REASON: test\n---\n" + "x" * 2001
    tracker, set_prompt, add_notification = _make_tracker(response)
    result = await tracker.analyze("s1", _make_messages_with_tools())
    assert result is None
    set_prompt.assert_not_called()


@pytest.mark.asyncio
async def test_analyze_skips_short_conversation():
    """짧은 대화는 분석하지 않는다."""
    tracker, set_prompt, _ = _make_tracker("NO_CHANGE")
    result = await tracker.analyze("s1", _make_messages_too_short())
    assert result is None
    set_prompt.assert_not_called()


@pytest.mark.asyncio
async def test_analyze_db_persistence():
    """DB가 있으면 개선된 프롬프트를 저장한다."""
    response = "REASON: persist test\n---\nNew prompt."
    tracker, set_prompt, _ = _make_tracker(response)
    tracker._db = AsyncMock()
    tracker._db.set_setting = AsyncMock()
    await tracker.analyze("s1", _make_messages_with_tools())
    tracker._db.set_setting.assert_called_once()
    call_args = tracker._db.set_setting.call_args
    assert call_args[0][0] == "behavior_prompt"
    assert call_args[0][1]["prompt"] == "New prompt."
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_behavior_tracker.py::test_analyze_no_change -v`
Expected: FAIL — AttributeError: 'BehaviorTracker' has no attribute 'analyze'

- [ ] **Step 3: analyze 메서드 구현**

`src/breadmind/core/behavior_tracker.py`에 추가:

```python
    # BehaviorTracker 클래스 내부에 추가

    def _build_analysis_prompt(self, current_prompt: str, metrics: dict) -> str:
        """분석 요청 프롬프트 생성."""
        return (
            "You are an AI prompt engineer. Analyze the following conversation metrics "
            "and improve the behavior prompt if needed.\n\n"
            f"## Current Behavior Prompt\n```\n{current_prompt}\n```\n\n"
            f"## Conversation Metrics\n"
            f"- Tool calls: {metrics['tool_call_count']} "
            f"(success: {metrics['tool_success_count']}, fail: {metrics['tool_failure_count']})\n"
            f"- Text-only response (no tools used): {metrics['text_only_response']}\n"
            f"- Tools used: {', '.join(tc['name'] for tc in metrics['tool_calls']) or 'none'}\n"
            f"- Negative user feedback detected: {metrics['negative_feedback']}\n"
            f"- Positive user feedback detected: {metrics['positive_feedback']}\n"
            f"- User messages:\n"
            + "\n".join(f"  - {m}" for m in metrics["user_messages"])
            + "\n\n"
            "## Instructions\n"
            "If the current prompt is working well (tools used appropriately, no negative feedback), "
            "respond with exactly: NO_CHANGE\n\n"
            "If improvements are needed, respond in this exact format:\n"
            "REASON: one-line summary of what changed\n"
            "---\n"
            "The complete improved behavior prompt text\n\n"
            "Rules:\n"
            "- Keep the prompt concise (under 2000 characters)\n"
            "- Do not add system-specific tool names\n"
            "- Focus on universal behavioral patterns\n"
            "- Preserve existing rules that are working\n"
            "- Only add or modify rules that address observed issues"
        )

    def _parse_response(self, content: str) -> tuple[str | None, str | None]:
        """LLM 응답을 파싱하여 (reason, new_prompt) 반환. 변경 없으면 (None, None)."""
        content = content.strip()
        if content == "NO_CHANGE" or content.startswith("NO_CHANGE"):
            # Only treat as no-change if the entire response is NO_CHANGE
            # or NO_CHANGE is followed by whitespace/newline only
            first_line = content.split("\n", 1)[0].strip()
            if first_line == "NO_CHANGE":
                return None, None

        if "---" not in content:
            return None, None

        parts = content.split("---", 1)
        header = parts[0].strip()
        prompt = parts[1].strip()

        reason = None
        for line in header.split("\n"):
            line = line.strip()
            if line.startswith("REASON:"):
                reason = line[len("REASON:"):].strip()
                break

        if not prompt or not reason:
            return None, None

        return reason, prompt

    async def analyze(
        self, session_id: str, messages: list[LLMMessage],
    ) -> dict | None:
        """대화 종료 후 분석. 개선이 있으면 dict(reason, prompt) 반환, 없으면 None."""
        if not self._should_analyze(messages):
            return None

        async with self._lock:
            metrics = self._extract_metrics(messages)
            current_prompt = self._get_behavior_prompt()
            analysis_prompt = self._build_analysis_prompt(current_prompt, metrics)

            try:
                response = await self._provider.chat(
                    messages=[LLMMessage(role="user", content=analysis_prompt)],
                )
            except Exception:
                logger.exception("Behavior analysis LLM call failed")
                return None

            if not response.content:
                return None

            reason, new_prompt = self._parse_response(response.content)
            if reason is None or new_prompt is None:
                return None

            if len(new_prompt) > _MAX_PROMPT_LENGTH:
                logger.warning(
                    f"Behavior prompt too long ({len(new_prompt)} chars), skipping"
                )
                return None

            # Apply
            self._set_behavior_prompt(new_prompt)

            # Persist
            if self._db:
                try:
                    await self._db.set_setting("behavior_prompt", {
                        "prompt": new_prompt,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "reason": reason,
                    })
                except Exception:
                    logger.exception("Failed to persist behavior prompt")

            # Notify
            self._add_notification(
                f"[BreadMind] 행동 프롬프트가 개선되었습니다: {reason}"
            )

            logger.info(f"Behavior prompt improved: {reason}")
            return {"reason": reason, "prompt": new_prompt}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_behavior_tracker.py -v`
Expected: 12 PASSED

- [ ] **Step 5: 커밋**

```bash
git add src/breadmind/core/behavior_tracker.py tests/test_behavior_tracker.py
git commit -m "feat: BehaviorTracker analyze with LLM analysis and prompt update"
```

---

## Chunk 2: CoreAgent 통합 및 시작 시 로드

### Task 4: CoreAgent — behavior_prompt, notifications, _safe_analyze

**Files:**
- Modify: `src/breadmind/core/agent.py`
- Test: `tests/test_behavior_tracker.py`

- [ ] **Step 1: CoreAgent 통합 테스트 작성**

```python
# tests/test_behavior_tracker.py에 추가
from breadmind.core.agent import CoreAgent
from breadmind.core.safety import SafetyGuard
from breadmind.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_agent_behavior_prompt_getter_setter():
    """CoreAgent의 behavior_prompt getter/setter가 동작한다."""
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=LLMResponse(
        content="hello", tool_calls=[],
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    ))
    agent = CoreAgent(
        provider=provider,
        tool_registry=ToolRegistry(),
        safety_guard=SafetyGuard(),
        behavior_prompt="initial behavior",
    )
    assert agent.get_behavior_prompt() == "initial behavior"
    agent.set_behavior_prompt("updated behavior")
    assert agent.get_behavior_prompt() == "updated behavior"
    # system_prompt should be rebuilt
    assert "updated behavior" in agent._system_prompt


@pytest.mark.asyncio
async def test_agent_notifications_prepended():
    """pending notification이 있으면 다음 응답 앞에 추가된다."""
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_behavior_tracker.py::test_agent_behavior_prompt_getter_setter -v`
Expected: FAIL — `__init__()` got unexpected keyword argument 'behavior_prompt'

- [ ] **Step 3: CoreAgent 수정**

`src/breadmind/core/agent.py` 수정:

**__init__ 시그니처에 추가:**
```python
    def __init__(
        self,
        provider: LLMProvider,
        tool_registry: ToolRegistry,
        safety_guard: SafetyGuard,
        system_prompt: str = "You are BreadMind, an AI infrastructure agent.",
        max_turns: int = 10,
        working_memory: WorkingMemory | None = None,
        tool_timeout: int = 30,
        chat_timeout: int = 120,
        audit_logger: AuditLogger | None = None,
        summarizer: object | None = None,
        tool_gap_detector: ToolGapDetector | None = None,
        context_builder: object | None = None,
        behavior_prompt: str | None = None,
    ):
```

**__init__ 본문에 추가 (기존 필드 할당 뒤):**
```python
        self._behavior_prompt = behavior_prompt
        self._notifications: list[str] = []
        self._behavior_tracker: object | None = None

        # If behavior_prompt provided, rebuild system_prompt
        if behavior_prompt is not None:
            from breadmind.config import build_system_prompt, DEFAULT_PERSONA
            self._system_prompt = build_system_prompt(
                DEFAULT_PERSONA, behavior_prompt=behavior_prompt,
            )
```

**새 메서드 추가 (set_system_prompt 아래):**
```python
    def get_behavior_prompt(self) -> str:
        from breadmind.config import _PROACTIVE_BEHAVIOR_PROMPT
        return self._behavior_prompt or _PROACTIVE_BEHAVIOR_PROMPT

    def set_behavior_prompt(self, prompt: str):
        from breadmind.config import build_system_prompt, DEFAULT_PERSONA
        self._behavior_prompt = prompt
        self._system_prompt = build_system_prompt(
            DEFAULT_PERSONA, behavior_prompt=prompt,
        )

    def add_notification(self, message: str):
        self._notifications.append(message)

    def set_behavior_tracker(self, tracker):
        self._behavior_tracker = tracker
```

**handle_message의 최종 응답 반환 부분 수정 (2곳):**

1. `if not response.has_tool_calls:` 블록 내 (line 234-242):
```python
            if not response.has_tool_calls:
                final_content = response.content or ""
                # Prepend pending notifications
                if self._notifications:
                    prefix = "\n".join(self._notifications) + "\n\n"
                    self._notifications.clear()
                    final_content = prefix + final_content
                if self._working_memory is not None:
                    self._working_memory.add_message(
                        session_id,
                        LLMMessage(role="assistant", content=final_content),
                    )
                logger.info(json.dumps({"event": "session_end", "user": user, "channel": channel}))
                # Fire-and-forget behavior analysis
                if self._behavior_tracker is not None:
                    asyncio.create_task(
                        self._safe_analyze(session_id, list(messages))
                    )
                return final_content
```

2. max_turns 도달 시 반환 부분 (line 365-366):
```python
        logger.info(json.dumps({"event": "session_end", "user": user, "channel": channel, "reason": "max_turns"}))
        final = "Maximum tool call turns reached. Please try a simpler request."
        if self._notifications:
            prefix = "\n".join(self._notifications) + "\n\n"
            self._notifications.clear()
            final = prefix + final
        if self._behavior_tracker is not None:
            asyncio.create_task(
                self._safe_analyze(session_id, list(messages))
            )
        return final
```

**_safe_analyze 메서드 추가:**
```python
    async def _safe_analyze(self, session_id: str, messages: list[LLMMessage]):
        """Fire-and-forget behavior analysis with error protection."""
        try:
            await self._behavior_tracker.analyze(session_id, messages)
        except Exception:
            logger.exception("Behavior analysis failed")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_behavior_tracker.py -v`
Expected: 14 PASSED

- [ ] **Step 5: 기존 agent 테스트도 깨지지 않는지 확인**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_agent.py -v`
Expected: ALL PASSED

- [ ] **Step 6: 커밋**

```bash
git add src/breadmind/core/agent.py tests/test_behavior_tracker.py
git commit -m "feat: CoreAgent behavior_prompt, notifications, and behavior analysis integration"
```

---

### Task 5: main.py — BehaviorTracker 생성 및 DB 로드

**Files:**
- Modify: `src/breadmind/main.py:317-333`

- [ ] **Step 1: main.py 수정**

`agent = CoreAgent(**agent_kwargs)` 이후에 BehaviorTracker 생성 및 연결:

```python
    from breadmind.config import build_system_prompt, DEFAULT_PERSONA

    # Load saved behavior prompt from DB
    saved_behavior_prompt = None
    if db is not None:
        try:
            bp_data = await db.get_setting("behavior_prompt")
            if bp_data and "prompt" in bp_data:
                saved_behavior_prompt = bp_data["prompt"]
        except Exception:
            pass

    system_prompt = build_system_prompt(
        DEFAULT_PERSONA, behavior_prompt=saved_behavior_prompt,
    )

    agent_kwargs = dict(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
        system_prompt=system_prompt,
        max_turns=config.llm.tool_call_max_turns,
        working_memory=working_memory,
        tool_gap_detector=tool_gap_detector,
        context_builder=context_builder,
        behavior_prompt=saved_behavior_prompt,
    )
    if audit_logger is not None:
        agent_kwargs["audit_logger"] = audit_logger

    agent = CoreAgent(**agent_kwargs)

    # Wire BehaviorTracker
    from breadmind.core.behavior_tracker import BehaviorTracker
    behavior_tracker = BehaviorTracker(
        provider=provider,
        get_behavior_prompt=agent.get_behavior_prompt,
        set_behavior_prompt=agent.set_behavior_prompt,
        add_notification=agent.add_notification,
        db=db,
    )
    agent.set_behavior_tracker(behavior_tracker)
```

- [ ] **Step 2: 수동 검증 — import 오류 없는지 확인**

Run: `cd D:/Projects/breadmind && python -c "from breadmind.core.behavior_tracker import BehaviorTracker; print('OK')"`
Expected: OK

- [ ] **Step 3: 커밋**

```bash
git add src/breadmind/main.py
git commit -m "feat: wire BehaviorTracker in main.py with DB persistence"
```

---

### Task 6: set_persona에서 behavior_prompt 유지

**Files:**
- Modify: `src/breadmind/core/agent.py`
- Test: `tests/test_behavior_tracker.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_behavior_tracker.py에 추가

def test_set_persona_preserves_behavior_prompt():
    """페르소나 변경 시 behavior_prompt가 유지된다."""
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_behavior_tracker.py::test_set_persona_preserves_behavior_prompt -v`
Expected: FAIL — "my custom rules" not in agent._system_prompt

- [ ] **Step 3: set_persona 수정**

```python
    def set_persona(self, persona: dict):
        from breadmind.config import build_system_prompt
        self._system_prompt = build_system_prompt(
            persona, behavior_prompt=self._behavior_prompt,
        )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_behavior_tracker.py -v`
Expected: 15 PASSED

- [ ] **Step 5: 커밋**

```bash
git add src/breadmind/core/agent.py tests/test_behavior_tracker.py
git commit -m "fix: set_persona preserves custom behavior_prompt"
```
