# Breadmind v2 Framework 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Breadmind을 도메인 무관 에이전트 프레임워크로 재작성. 프로토콜 기반 코어 + 플러그인 아키텍처.

**Architecture:** 마이크로 코어(~1000줄)가 6개 프로토콜과 DI 컨테이너/이벤트 버스를 정의하고, 모든 기능(에이전트 루프, LLM 프로바이더, 프롬프트, 메모리, 도구, 런타임)은 프로토콜을 구현하는 플러그인으로 존재. 기존 Breadmind 인프라 코드는 도메인 플러그인으로 마이그레이션.

**Tech Stack:** Python 3.12+, pytest (asyncio auto), Jinja2, anthropic SDK, openai SDK, asyncpg, pydantic, FastAPI, pyyaml

**Spec:** `Documents/Plans/2026-04-04-breadmind-v2-framework-design.md`

---

## 파일 구조

새로 생성될 파일:

```
src/breadmind/
├── core/
│   ├── __init__.py
│   ├── protocols/
│   │   ├── __init__.py
│   │   ├── provider.py        # ProviderProtocol, CacheStrategy, LLMResponse, Message
│   │   ├── prompt.py          # PromptProtocol, PromptBlock, PromptContext, CompactResult
│   │   ├── tool.py            # ToolProtocol, ToolDefinition, ToolCall, ToolResult, ToolFilter
│   │   ├── memory.py          # MemoryProtocol, Episode, KGTriple
│   │   ├── agent.py           # AgentProtocol, AgentContext, AgentResponse
│   │   └── runtime.py         # RuntimeProtocol, UserInput, AgentOutput
│   ├── container.py           # Container (DI 컨테이너)
│   ├── events.py              # EventBus (타입드 이벤트)
│   └── plugin.py              # PluginLoader (발견, 로드, 의존성 해석)
│
├── plugins/
│   └── builtin/
│       ├── __init__.py
│       ├── providers/
│       │   ├── __init__.py
│       │   ├── claude_adapter.py
│       │   ├── gemini_adapter.py
│       │   ├── grok_adapter.py
│       │   └── ollama_adapter.py
│       ├── prompt_builder/
│       │   ├── __init__.py
│       │   ├── jinja_builder.py     # Jinja2 기반 PromptProtocol 구현
│       │   ├── compactor.py         # LLM 기반 컨텍스트 압축
│       │   ├── reminder.py          # system-reminder 주입
│       │   └── templates/           # 기존 .j2 파일 이동
│       ├── agent_loop/
│       │   ├── __init__.py
│       │   ├── message_loop.py      # 기본 에이전트 루프
│       │   └── spawner.py           # 재귀 spawn + swarm
│       ├── memory/
│       │   ├── __init__.py
│       │   ├── working_memory.py
│       │   ├── episodic_memory.py
│       │   ├── semantic_memory.py
│       │   ├── context_builder.py
│       │   ├── smart_retriever.py
│       │   └── dreamer.py
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── registry.py          # HybridToolRegistry
│       │   ├── executor.py          # ToolExecutor (안전+승인+실행)
│       │   └── core/                # shell, file, web 등 기본 도구
│       ├── safety/
│       │   ├── __init__.py
│       │   └── guard.py             # SafetyGuard + autonomy level
│       └── runtimes/
│           ├── __init__.py
│           ├── cli_runtime.py
│           ├── server_runtime.py
│           └── embedded_runtime.py
│
├── sdk/
│   ├── __init__.py
│   └── agent.py                     # Agent 클래스 (SDK 진입점)
│
└── dsl/
    ├── __init__.py
    └── yaml_loader.py               # YAML → Agent 변환
```

테스트 파일:

```
tests/
├── core/
│   ├── test_protocols.py
│   ├── test_container.py
│   ├── test_events.py
│   └── test_plugin.py
├── plugins/
│   ├── test_claude_adapter.py
│   ├── test_gemini_adapter.py
│   ├── test_jinja_builder.py
│   ├── test_compactor.py
│   ├── test_reminder.py
│   ├── test_message_loop.py
│   ├── test_spawner.py
│   ├── test_working_memory.py
│   ├── test_episodic_memory.py
│   ├── test_dreamer.py
│   ├── test_hybrid_registry.py
│   ├── test_executor.py
│   ├── test_safety_guard.py
│   ├── test_cli_runtime.py
│   └── test_server_runtime.py
├── sdk/
│   ├── test_agent_sdk.py
│   └── test_yaml_loader.py
└── integration/
    ├── test_single_turn.py
    ├── test_multi_turn.py
    └── test_sub_agent.py
```

---

## Phase 1: 기반 (코어)

### Task 1: 공통 메시지 타입 정의

**Files:**
- Create: `src/breadmind/core/__init__.py`
- Create: `src/breadmind/core/protocols/__init__.py`
- Create: `src/breadmind/core/protocols/provider.py`
- Test: `tests/core/test_protocols.py`

- [ ] **Step 1: 테스트 작성 — Message, LLMResponse 데이터클래스**

```python
# tests/core/test_protocols.py
from breadmind.core.protocols.provider import Message, LLMResponse, ToolCallRequest, TokenUsage

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
    resp = LLMResponse(
        content=None,
        tool_calls=[tc],
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="tool_use",
    )
    assert resp.has_tool_calls is True
    assert resp.tool_calls[0].name == "shell_exec"

def test_llm_response_text_only():
    resp = LLMResponse(
        content="hello",
        tool_calls=[],
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )
    assert resp.has_tool_calls is False

def test_token_usage_total():
    usage = TokenUsage(input_tokens=100, output_tokens=50)
    assert usage.total_tokens == 150
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/core/test_protocols.py -v`
Expected: FAIL (모듈 없음)

- [ ] **Step 3: 구현 — 공통 타입**

```python
# src/breadmind/core/__init__.py
"""Breadmind v2 마이크로 코어."""

# src/breadmind/core/protocols/__init__.py
"""프로토콜 정의 (계약만, 구현 없음)."""
from breadmind.core.protocols.provider import (
    Message,
    LLMResponse,
    TokenUsage,
    ToolCallRequest,
)

__all__ = ["Message", "LLMResponse", "TokenUsage", "ToolCallRequest"]
```

```python
# src/breadmind/core/protocols/provider.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Protocol, runtime_checkable


@dataclass
class ToolCallRequest:
    """LLM이 요청한 도구 호출."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class TokenUsage:
    """토큰 사용량."""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class Message:
    """대화 메시지."""
    role: str  # "user" | "assistant" | "system" | "tool"
    content: str | None = None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None
    is_meta: bool = False  # system-reminder 등 메타 메시지 여부


@dataclass
class LLMResponse:
    """LLM 응답."""
    content: str | None
    tool_calls: list[ToolCallRequest]
    usage: TokenUsage
    stop_reason: str

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class CacheStrategy:
    """프로바이더별 캐시 전략."""
    name: str
    config: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ProviderProtocol(Protocol):
    """LLM 프로바이더 계약."""

    async def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        think_budget: int | None = None,
    ) -> LLMResponse: ...

    def get_cache_strategy(self) -> CacheStrategy | None:
        return None

    def supports_feature(self, feature: str) -> bool:
        return False

    def transform_system_prompt(self, blocks: list[Any]) -> Any:
        return blocks

    def transform_messages(self, messages: list[Message]) -> list[Any]:
        return messages

    @property
    def fallback(self) -> ProviderProtocol | None:
        return None
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `pytest tests/core/test_protocols.py -v`
Expected: 5 passed

- [ ] **Step 5: 커밋**

```bash
git add src/breadmind/core/__init__.py src/breadmind/core/protocols/__init__.py src/breadmind/core/protocols/provider.py tests/core/test_protocols.py
git commit -m "feat(core): add Message, LLMResponse types and ProviderProtocol"
```

---

### Task 2: PromptProtocol + PromptBlock 정의

**Files:**
- Create: `src/breadmind/core/protocols/prompt.py`
- Test: `tests/core/test_protocols.py` (추가)

- [ ] **Step 1: 테스트 작성**

```python
# tests/core/test_protocols.py (추가)
from breadmind.core.protocols.prompt import PromptBlock, PromptContext, CompactResult

def test_prompt_block_creation():
    block = PromptBlock(
        section="iron_laws",
        content="Never guess.",
        cacheable=True,
        priority=0,
    )
    assert block.section == "iron_laws"
    assert block.cacheable is True
    assert block.priority == 0
    assert block.provider_hints == {}

def test_prompt_block_with_hints():
    block = PromptBlock(
        section="identity",
        content="You are BreadMind.",
        cacheable=True,
        priority=1,
        provider_hints={"claude": {"scope": "global"}},
    )
    assert block.provider_hints["claude"]["scope"] == "global"

def test_prompt_context_defaults():
    ctx = PromptContext()
    assert ctx.persona_name == "BreadMind"
    assert ctx.language == "ko"
    assert ctx.available_tools == []

def test_compact_result():
    from breadmind.core.protocols.provider import Message
    boundary = Message(role="system", content="Summary of prior conversation.")
    preserved = [Message(role="user", content="latest msg")]
    result = CompactResult(boundary=boundary, preserved=preserved, tokens_saved=500)
    assert result.tokens_saved == 500
    assert len(result.preserved) == 1
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/core/test_protocols.py::test_prompt_block_creation -v`
Expected: FAIL

- [ ] **Step 3: 구현**

```python
# src/breadmind/core/protocols/prompt.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from breadmind.core.protocols.provider import Message


@dataclass
class PromptBlock:
    """시스템 프롬프트의 단위 블록."""
    section: str
    content: str
    cacheable: bool = False
    priority: int = 5  # 0=불변(iron_laws), 높을수록 먼저 제거
    provider_hints: dict[str, Any] = field(default_factory=dict)


@dataclass
class PromptContext:
    """프롬프트 빌드에 필요한 런타임 컨텍스트."""
    persona_name: str = "BreadMind"
    language: str = "ko"
    specialties: list[str] = field(default_factory=list)
    os_info: str = ""
    current_date: str = ""
    available_tools: list[str] = field(default_factory=list)
    provider_model: str = ""
    custom_instructions: str | None = None
    role: str | None = None
    persona: str = "professional"


@dataclass
class CompactResult:
    """컨텍스트 압축 결과."""
    boundary: Message
    preserved: list[Message]
    tokens_saved: int


@runtime_checkable
class PromptProtocol(Protocol):
    """프롬프트 빌드/캐시/압축 계약."""

    def build(self, context: PromptContext) -> list[PromptBlock]: ...

    def rebuild_dynamic(self, context: PromptContext) -> list[PromptBlock]: ...

    async def compact(
        self, messages: list[Message], budget_tokens: int,
    ) -> CompactResult: ...

    def inject_reminder(self, key: str, content: str) -> Message: ...
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `pytest tests/core/test_protocols.py -v`
Expected: All passed

- [ ] **Step 5: 커밋**

```bash
git add src/breadmind/core/protocols/prompt.py tests/core/test_protocols.py
git commit -m "feat(core): add PromptProtocol, PromptBlock, PromptContext"
```

---

### Task 3: ToolProtocol 정의

**Files:**
- Create: `src/breadmind/core/protocols/tool.py`
- Test: `tests/core/test_protocols.py` (추가)

- [ ] **Step 1: 테스트 작성**

```python
# tests/core/test_protocols.py (추가)
from breadmind.core.protocols.tool import ToolDefinition, ToolCall, ToolResult, ToolFilter, ToolSchema

def test_tool_definition():
    td = ToolDefinition(
        name="shell_exec",
        description="Execute shell command",
        parameters={"type": "object", "properties": {"command": {"type": "string"}}},
    )
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
    assert "shell_exec" in f.always_include

def test_tool_filter_intent():
    f = ToolFilter(intent="k8s_diagnose", keywords=["pod", "crash"])
    assert f.intent == "k8s_diagnose"

def test_tool_schema_deferred():
    s = ToolSchema(name="k8s_pods_list", deferred=True)
    assert s.deferred is True
    assert s.definition is None

def test_tool_schema_full():
    td = ToolDefinition(name="shell_exec", description="exec", parameters={})
    s = ToolSchema(name="shell_exec", deferred=False, definition=td)
    assert s.definition is not None
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/core/test_protocols.py::test_tool_definition -v`
Expected: FAIL

- [ ] **Step 3: 구현**

```python
# src/breadmind/core/protocols/tool.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolDefinition:
    """도구 정의."""
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolSchema:
    """LLM에 전달되는 도구 스키마. deferred=True이면 이름만 노출."""
    name: str
    deferred: bool = False
    definition: ToolDefinition | None = None


@dataclass
class ToolCall:
    """에이전트 루프에서 실행할 도구 호출."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """도구 실행 결과."""
    success: bool
    output: str
    error: str | None = None


@dataclass
class ToolFilter:
    """도구 필터링 조건."""
    intent: str | None = None
    keywords: list[str] = field(default_factory=list)
    always_include: list[str] = field(default_factory=list)
    max_tools: int | None = None
    use_deferred: bool = False


@dataclass
class ExecutionContext:
    """도구 실행 시 전달되는 컨텍스트."""
    user: str = ""
    channel: str = ""
    session_id: str = ""
    autonomy: str = "confirm-destructive"


@runtime_checkable
class ToolProtocol(Protocol):
    """도구 등록/실행/검색 계약."""

    def register(self, tool: ToolDefinition) -> None: ...
    def unregister(self, name: str) -> None: ...
    def get_schemas(self, filter: ToolFilter | None = None) -> list[ToolSchema]: ...
    async def execute(self, call: ToolCall, ctx: ExecutionContext) -> ToolResult: ...
    def get_deferred_tools(self) -> list[str]: ...
    def resolve_deferred(self, names: list[str]) -> list[ToolSchema]: ...
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `pytest tests/core/test_protocols.py -v`
Expected: All passed

- [ ] **Step 5: 커밋**

```bash
git add src/breadmind/core/protocols/tool.py tests/core/test_protocols.py
git commit -m "feat(core): add ToolProtocol with hybrid filter support"
```

---

### Task 4: MemoryProtocol 정의

**Files:**
- Create: `src/breadmind/core/protocols/memory.py`
- Test: `tests/core/test_protocols.py` (추가)

- [ ] **Step 1: 테스트 작성**

```python
# tests/core/test_protocols.py (추가)
from breadmind.core.protocols.memory import Episode, KGTriple

def test_episode_creation():
    ep = Episode(
        id="ep_1",
        content="User asked about pod crashes",
        keywords=["pod", "crash"],
        timestamp="2026-04-04T12:00:00Z",
    )
    assert ep.id == "ep_1"
    assert "pod" in ep.keywords

def test_kg_triple():
    t = KGTriple(subject="pod-abc", predicate="runs_on", object="node-1")
    assert t.subject == "pod-abc"
    assert t.predicate == "runs_on"
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/core/test_protocols.py::test_episode_creation -v`
Expected: FAIL

- [ ] **Step 3: 구현**

```python
# src/breadmind/core/protocols/memory.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from breadmind.core.protocols.prompt import PromptBlock
from breadmind.core.protocols.provider import Message


@dataclass
class Episode:
    """에피소딕 메모리 항목."""
    id: str
    content: str
    keywords: list[str] = field(default_factory=list)
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KGTriple:
    """지식그래프 트리플."""
    subject: str
    predicate: str
    object: str
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class MemoryProtocol(Protocol):
    """메모리 읽기/쓰기/검색/압축 계약."""

    # Working (세션)
    async def working_get(self, session_id: str) -> list[Message]: ...
    async def working_put(self, session_id: str, messages: list[Message]) -> None: ...
    async def working_compress(self, session_id: str, budget: int) -> None: ...

    # Episodic (경험)
    async def episodic_search(self, query: str, limit: int = 5) -> list[Episode]: ...
    async def episodic_save(self, episode: Episode) -> None: ...

    # Semantic (지식그래프)
    async def semantic_query(self, entities: list[str]) -> list[KGTriple]: ...
    async def semantic_upsert(self, triples: list[KGTriple]) -> None: ...

    # 컨텍스트 빌드 + dream
    async def build_context_block(
        self, session_id: str, query: str, budget_tokens: int,
    ) -> PromptBlock: ...

    async def dream(self, session_id: str) -> None: ...
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `pytest tests/core/test_protocols.py -v`
Expected: All passed

- [ ] **Step 5: 커밋**

```bash
git add src/breadmind/core/protocols/memory.py tests/core/test_protocols.py
git commit -m "feat(core): add MemoryProtocol with 3-layer + dream support"
```

---

### Task 5: AgentProtocol + RuntimeProtocol 정의

**Files:**
- Create: `src/breadmind/core/protocols/agent.py`
- Create: `src/breadmind/core/protocols/runtime.py`
- Test: `tests/core/test_protocols.py` (추가)

- [ ] **Step 1: 테스트 작성**

```python
# tests/core/test_protocols.py (추가)
from breadmind.core.protocols.agent import AgentContext, AgentResponse

def test_agent_context_defaults():
    ctx = AgentContext(user="admin", channel="cli", session_id="s1")
    assert ctx.depth == 0
    assert ctx.max_depth == 5
    assert ctx.parent_agent is None

def test_agent_context_nested():
    ctx = AgentContext(
        user="admin", channel="cli", session_id="s1",
        parent_agent="agent_root", depth=2,
    )
    assert ctx.depth == 2
    assert ctx.parent_agent == "agent_root"

def test_agent_response():
    resp = AgentResponse(content="Done.", tool_calls_count=3, tokens_used=150)
    assert resp.content == "Done."
    assert resp.tool_calls_count == 3
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/core/test_protocols.py::test_agent_context_defaults -v`
Expected: FAIL

- [ ] **Step 3: 구현 — AgentProtocol**

```python
# src/breadmind/core/protocols/agent.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class AgentContext:
    """에이전트 실행 컨텍스트."""
    user: str
    channel: str
    session_id: str
    parent_agent: str | None = None
    depth: int = 0
    max_depth: int = 5
    isolation: str | None = None  # "worktree", "container", None


@dataclass
class AgentResponse:
    """에이전트 응답."""
    content: str
    tool_calls_count: int = 0
    tokens_used: int = 0


@runtime_checkable
class AgentProtocol(Protocol):
    """에이전트 생명주기 계약."""

    @property
    def agent_id(self) -> str: ...

    async def handle_message(self, message: str, ctx: AgentContext) -> AgentResponse: ...

    async def spawn(
        self,
        prompt: str,
        tools: list[str] | None = None,
        isolation: str | None = None,
    ) -> AgentProtocol: ...

    async def send_message(self, target: str, message: str) -> str: ...

    def set_role(self, role: str) -> None: ...
```

- [ ] **Step 4: 구현 — RuntimeProtocol**

```python
# src/breadmind/core/protocols/runtime.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class UserInput:
    """런타임에서 수신한 사용자 입력."""
    text: str
    user: str = "anonymous"
    channel: str = "default"
    session_id: str = ""
    attachments: list[str] = field(default_factory=list)


@dataclass
class AgentOutput:
    """에이전트가 런타임에 전송하는 출력."""
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Progress:
    """진행 상황 알림."""
    status: str  # "thinking", "tool_executing", "completed"
    detail: str = ""


@runtime_checkable
class RuntimeProtocol(Protocol):
    """실행 환경 추상화 계약."""

    async def start(self, container: Any) -> None: ...
    async def stop(self) -> None: ...
    async def receive(self) -> UserInput: ...
    async def send(self, output: AgentOutput) -> None: ...
    async def send_progress(self, progress: Progress) -> None: ...
```

- [ ] **Step 5: 테스트 실행 — 통과 확인**

Run: `pytest tests/core/test_protocols.py -v`
Expected: All passed

- [ ] **Step 6: 커밋**

```bash
git add src/breadmind/core/protocols/agent.py src/breadmind/core/protocols/runtime.py tests/core/test_protocols.py
git commit -m "feat(core): add AgentProtocol and RuntimeProtocol"
```

---

### Task 6: 타입드 이벤트 버스

**Files:**
- Create: `src/breadmind/core/events.py`
- Test: `tests/core/test_events.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/core/test_events.py
import pytest
from breadmind.core.events import EventBus

@pytest.fixture
def bus():
    return EventBus()

def test_on_and_emit(bus: EventBus):
    received = []
    bus.on("test.event", lambda data: received.append(data))
    bus.emit("test.event", {"key": "value"})
    assert len(received) == 1
    assert received[0]["key"] == "value"

def test_multiple_listeners(bus: EventBus):
    results = []
    bus.on("multi", lambda d: results.append("a"))
    bus.on("multi", lambda d: results.append("b"))
    bus.emit("multi", {})
    assert results == ["a", "b"]

def test_no_listener_does_not_raise(bus: EventBus):
    bus.emit("unknown.event", {})  # should not raise

def test_off_removes_listener(bus: EventBus):
    results = []
    handler = lambda d: results.append(d)
    bus.on("removable", handler)
    bus.off("removable", handler)
    bus.emit("removable", "data")
    assert results == []

@pytest.mark.asyncio
async def test_async_emit(bus: EventBus):
    results = []
    async def async_handler(data):
        results.append(data)
    bus.on("async.event", async_handler)
    await bus.async_emit("async.event", "hello")
    assert results == ["hello"]
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/core/test_events.py -v`
Expected: FAIL

- [ ] **Step 3: 구현**

```python
# src/breadmind/core/events.py
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Callable


class EventBus:
    """타입드 이벤트 버스. 플러그인 간 느슨한 결합."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable]] = defaultdict(list)

    def on(self, event: str, handler: Callable) -> None:
        self._listeners[event].append(handler)

    def off(self, event: str, handler: Callable) -> None:
        listeners = self._listeners.get(event, [])
        if handler in listeners:
            listeners.remove(handler)

    def emit(self, event: str, data: Any = None) -> None:
        for handler in self._listeners.get(event, []):
            if asyncio.iscoroutinefunction(handler):
                continue  # 동기 emit에서는 async 핸들러 스킵
            handler(data)

    async def async_emit(self, event: str, data: Any = None) -> None:
        for handler in self._listeners.get(event, []):
            if asyncio.iscoroutinefunction(handler):
                await handler(data)
            else:
                handler(data)
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `pytest tests/core/test_events.py -v`
Expected: All passed

- [ ] **Step 5: 커밋**

```bash
git add src/breadmind/core/events.py tests/core/test_events.py
git commit -m "feat(core): add typed EventBus for plugin communication"
```

---

### Task 7: DI 컨테이너

**Files:**
- Create: `src/breadmind/core/container.py`
- Test: `tests/core/test_container.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/core/test_container.py
import pytest
from typing import Protocol, runtime_checkable
from breadmind.core.container import Container

@runtime_checkable
class GreeterProtocol(Protocol):
    def greet(self, name: str) -> str: ...

class EnglishGreeter:
    def greet(self, name: str) -> str:
        return f"Hello, {name}!"

class KoreanGreeter:
    def greet(self, name: str) -> str:
        return f"안녕, {name}!"

@runtime_checkable
class ServiceProtocol(Protocol):
    def do_work(self) -> str: ...

class ServiceWithDep:
    def __init__(self, greeter: GreeterProtocol):
        self._greeter = greeter

    def do_work(self) -> str:
        return self._greeter.greet("world")

def test_register_and_resolve():
    c = Container()
    c.register(GreeterProtocol, EnglishGreeter())
    greeter = c.resolve(GreeterProtocol)
    assert greeter.greet("test") == "Hello, test!"

def test_resolve_unregistered_raises():
    c = Container()
    with pytest.raises(KeyError):
        c.resolve(GreeterProtocol)

def test_override_registration():
    c = Container()
    c.register(GreeterProtocol, EnglishGreeter())
    c.register(GreeterProtocol, KoreanGreeter())
    greeter = c.resolve(GreeterProtocol)
    assert greeter.greet("test") == "안녕, test!"

def test_register_factory():
    c = Container()
    c.register(GreeterProtocol, EnglishGreeter())
    c.register_factory(ServiceProtocol, lambda cont: ServiceWithDep(cont.resolve(GreeterProtocol)))
    svc = c.resolve(ServiceProtocol)
    assert svc.do_work() == "Hello, world!"

def test_has():
    c = Container()
    assert c.has(GreeterProtocol) is False
    c.register(GreeterProtocol, EnglishGreeter())
    assert c.has(GreeterProtocol) is True
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/core/test_container.py -v`
Expected: FAIL

- [ ] **Step 3: 구현**

```python
# src/breadmind/core/container.py
from __future__ import annotations

from typing import Any, Callable, TypeVar

T = TypeVar("T")


class Container:
    """DI 컨테이너. 프로토콜 → 구현체 매핑."""

    def __init__(self) -> None:
        self._instances: dict[type, Any] = {}
        self._factories: dict[type, Callable[[Container], Any]] = {}

    def register(self, protocol: type[T], instance: T) -> None:
        self._instances[protocol] = instance

    def register_factory(self, protocol: type[T], factory: Callable[[Container], T]) -> None:
        self._factories[protocol] = factory

    def resolve(self, protocol: type[T]) -> T:
        if protocol in self._instances:
            return self._instances[protocol]
        if protocol in self._factories:
            instance = self._factories[protocol](self)
            self._instances[protocol] = instance
            return instance
        raise KeyError(f"No implementation registered for {protocol.__name__}")

    def has(self, protocol: type) -> bool:
        return protocol in self._instances or protocol in self._factories
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `pytest tests/core/test_container.py -v`
Expected: All passed

- [ ] **Step 5: 커밋**

```bash
git add src/breadmind/core/container.py tests/core/test_container.py
git commit -m "feat(core): add DI Container with factory support"
```

---

### Task 8: 플러그인 로더

**Files:**
- Create: `src/breadmind/core/plugin.py`
- Test: `tests/core/test_plugin.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/core/test_plugin.py
import pytest
from breadmind.core.plugin import PluginLoader, PluginManifest
from breadmind.core.container import Container
from breadmind.core.events import EventBus

@pytest.fixture
def loader():
    return PluginLoader(container=Container(), events=EventBus())

def test_manifest_creation():
    m = PluginManifest(
        name="test-plugin",
        version="1.0.0",
        provides=["GreeterProtocol"],
        depends_on=[],
    )
    assert m.name == "test-plugin"

def test_register_plugin(loader: PluginLoader):
    class FakePlugin:
        manifest = PluginManifest(name="fake", version="0.1", provides=[], depends_on=[])
        async def setup(self, container, events):
            pass
        async def teardown(self):
            pass

    loader.register(FakePlugin())
    assert "fake" in loader.list_plugins()

def test_register_duplicate_raises(loader: PluginLoader):
    class FakePlugin:
        manifest = PluginManifest(name="dupe", version="0.1", provides=[], depends_on=[])
        async def setup(self, container, events):
            pass
        async def teardown(self):
            pass

    loader.register(FakePlugin())
    with pytest.raises(ValueError, match="already registered"):
        loader.register(FakePlugin())

@pytest.mark.asyncio
async def test_setup_all(loader: PluginLoader):
    setup_called = []

    class TestPlugin:
        manifest = PluginManifest(name="test", version="0.1", provides=[], depends_on=[])
        async def setup(self, container, events):
            setup_called.append(True)
        async def teardown(self):
            pass

    loader.register(TestPlugin())
    await loader.setup_all()
    assert len(setup_called) == 1

@pytest.mark.asyncio
async def test_teardown_all(loader: PluginLoader):
    torn_down = []

    class TestPlugin:
        manifest = PluginManifest(name="td", version="0.1", provides=[], depends_on=[])
        async def setup(self, container, events):
            pass
        async def teardown(self):
            torn_down.append(True)

    loader.register(TestPlugin())
    await loader.setup_all()
    await loader.teardown_all()
    assert len(torn_down) == 1

@pytest.mark.asyncio
async def test_dependency_order(loader: PluginLoader):
    order = []

    class PluginA:
        manifest = PluginManifest(name="A", version="0.1", provides=["A"], depends_on=[])
        async def setup(self, container, events):
            order.append("A")
        async def teardown(self):
            pass

    class PluginB:
        manifest = PluginManifest(name="B", version="0.1", provides=["B"], depends_on=["A"])
        async def setup(self, container, events):
            order.append("B")
        async def teardown(self):
            pass

    loader.register(PluginB())
    loader.register(PluginA())
    await loader.setup_all()
    assert order == ["A", "B"]
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/core/test_plugin.py -v`
Expected: FAIL

- [ ] **Step 3: 구현**

```python
# src/breadmind/core/plugin.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from breadmind.core.container import Container
from breadmind.core.events import EventBus


@dataclass
class PluginManifest:
    """플러그인 메타데이터."""
    name: str
    version: str
    provides: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)


class PluginLoader:
    """플러그인 발견, 로드, 의존성 해석."""

    def __init__(self, container: Container, events: EventBus) -> None:
        self._container = container
        self._events = events
        self._plugins: dict[str, Any] = {}

    def register(self, plugin: Any) -> None:
        name = plugin.manifest.name
        if name in self._plugins:
            raise ValueError(f"Plugin '{name}' already registered")
        self._plugins[name] = plugin

    def list_plugins(self) -> list[str]:
        return list(self._plugins.keys())

    async def setup_all(self) -> None:
        ordered = self._resolve_order()
        for name in ordered:
            plugin = self._plugins[name]
            await plugin.setup(self._container, self._events)

    async def teardown_all(self) -> None:
        for plugin in reversed(list(self._plugins.values())):
            await plugin.teardown()

    def _resolve_order(self) -> list[str]:
        """토폴로지 정렬로 의존성 순서 결정."""
        visited: set[str] = set()
        order: list[str] = []
        provides_map: dict[str, str] = {}

        for name, plugin in self._plugins.items():
            for p in plugin.manifest.provides:
                provides_map[p] = name

        def visit(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            plugin = self._plugins.get(name)
            if plugin:
                for dep in plugin.manifest.depends_on:
                    provider_name = provides_map.get(dep, dep)
                    if provider_name in self._plugins:
                        visit(provider_name)
            order.append(name)

        for name in self._plugins:
            visit(name)

        return order
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `pytest tests/core/test_plugin.py -v`
Expected: All passed

- [ ] **Step 5: 커밋**

```bash
git add src/breadmind/core/plugin.py tests/core/test_plugin.py
git commit -m "feat(core): add PluginLoader with dependency resolution"
```

---

### Task 9: protocols/__init__.py에 전체 export 정리

**Files:**
- Modify: `src/breadmind/core/protocols/__init__.py`

- [ ] **Step 1: __init__.py 업데이트**

```python
# src/breadmind/core/protocols/__init__.py
"""Breadmind v2 프로토콜 정의."""

from breadmind.core.protocols.provider import (
    CacheStrategy,
    LLMResponse,
    Message,
    ProviderProtocol,
    TokenUsage,
    ToolCallRequest,
)
from breadmind.core.protocols.prompt import (
    CompactResult,
    PromptBlock,
    PromptContext,
    PromptProtocol,
)
from breadmind.core.protocols.tool import (
    ExecutionContext,
    ToolCall,
    ToolDefinition,
    ToolFilter,
    ToolProtocol,
    ToolResult,
    ToolSchema,
)
from breadmind.core.protocols.memory import (
    Episode,
    KGTriple,
    MemoryProtocol,
)
from breadmind.core.protocols.agent import (
    AgentContext,
    AgentProtocol,
    AgentResponse,
)
from breadmind.core.protocols.runtime import (
    AgentOutput,
    Progress,
    RuntimeProtocol,
    UserInput,
)

__all__ = [
    # Provider
    "CacheStrategy", "LLMResponse", "Message", "ProviderProtocol", "TokenUsage", "ToolCallRequest",
    # Prompt
    "CompactResult", "PromptBlock", "PromptContext", "PromptProtocol",
    # Tool
    "ExecutionContext", "ToolCall", "ToolDefinition", "ToolFilter", "ToolProtocol", "ToolResult", "ToolSchema",
    # Memory
    "Episode", "KGTriple", "MemoryProtocol",
    # Agent
    "AgentContext", "AgentProtocol", "AgentResponse",
    # Runtime
    "AgentOutput", "Progress", "RuntimeProtocol", "UserInput",
]
```

- [ ] **Step 2: import 테스트**

Run: `python -c "from breadmind.core.protocols import ProviderProtocol, PromptProtocol, ToolProtocol, MemoryProtocol, AgentProtocol, RuntimeProtocol; print('All protocols importable')"`
Expected: "All protocols importable"

- [ ] **Step 3: 커밋**

```bash
git add src/breadmind/core/protocols/__init__.py
git commit -m "feat(core): export all protocols from core.protocols"
```

---

## Phase 2: 엔진

### Task 10: Claude 프로바이더 어댑터

**Files:**
- Create: `src/breadmind/plugins/builtin/__init__.py`
- Create: `src/breadmind/plugins/builtin/providers/__init__.py`
- Create: `src/breadmind/plugins/builtin/providers/claude_adapter.py`
- Test: `tests/plugins/test_claude_adapter.py`

기존 `src/breadmind/llm/claude.py`를 참고하여 ProviderProtocol을 구현하되, 캐시 전략과 system-reminder 변환을 추가합니다.

- [ ] **Step 1: 테스트 작성**

```python
# tests/plugins/test_claude_adapter.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from breadmind.core.protocols import Message, PromptBlock, TokenUsage, LLMResponse
from breadmind.plugins.builtin.providers.claude_adapter import ClaudeAdapter

@pytest.fixture
def adapter():
    return ClaudeAdapter(api_key="test-key", model="claude-sonnet-4-6")

def test_supports_feature(adapter: ClaudeAdapter):
    assert adapter.supports_feature("thinking_blocks") is True
    assert adapter.supports_feature("system_reminder") is True
    assert adapter.supports_feature("prompt_caching") is True
    assert adapter.supports_feature("tool_search") is True
    assert adapter.supports_feature("nonexistent") is False

def test_get_cache_strategy(adapter: ClaudeAdapter):
    strategy = adapter.get_cache_strategy()
    assert strategy is not None
    assert strategy.name == "claude_ephemeral"

def test_transform_system_prompt_cacheable(adapter: ClaudeAdapter):
    blocks = [
        PromptBlock(section="iron_laws", content="Never guess.", cacheable=True, priority=0,
                    provider_hints={"claude": {"scope": "global"}}),
        PromptBlock(section="env", content="OS: Linux", cacheable=False, priority=5),
    ]
    result = adapter.transform_system_prompt(blocks)
    assert len(result) == 2
    assert result[0]["cache_control"]["scope"] == "global"
    assert "cache_control" not in result[1]

def test_transform_messages_injects_reminder(adapter: ClaudeAdapter):
    messages = [
        Message(role="user", content="<system-reminder>context</system-reminder>", is_meta=True),
        Message(role="user", content="hello"),
    ]
    result = adapter.transform_messages(messages)
    assert result[0]["role"] == "user"
    assert "<system-reminder>" in result[0]["content"]

def test_fallback_none(adapter: ClaudeAdapter):
    assert adapter.fallback is None

def test_fallback_set():
    fallback_provider = MagicMock()
    adapter = ClaudeAdapter(api_key="test", model="claude-sonnet-4-6", fallback_provider=fallback_provider)
    assert adapter.fallback is fallback_provider
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/plugins/test_claude_adapter.py -v`
Expected: FAIL

- [ ] **Step 3: 구현**

```python
# src/breadmind/plugins/builtin/__init__.py
"""빌트인 플러그인."""

# src/breadmind/plugins/builtin/providers/__init__.py
"""LLM 프로바이더 어댑터."""
```

```python
# src/breadmind/plugins/builtin/providers/claude_adapter.py
from __future__ import annotations

from typing import Any

from breadmind.core.protocols import (
    CacheStrategy,
    LLMResponse,
    Message,
    PromptBlock,
    ProviderProtocol,
    TokenUsage,
    ToolCallRequest,
)

SUPPORTED_FEATURES = frozenset({
    "thinking_blocks", "system_reminder", "prompt_caching", "tool_search",
})


class ClaudeAdapter:
    """Claude API ProviderProtocol 구현 + 캐싱/thinking 최적화."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-6",
        fallback_provider: ProviderProtocol | None = None,
        max_tokens: int = 16384,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._fallback = fallback_provider
        self._max_tokens = max_tokens
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        return self._client

    async def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        think_budget: int | None = None,
    ) -> LLMResponse:
        client = self._get_client()
        api_messages = self.transform_messages(messages)

        system_msgs = [m for m in api_messages if m["role"] == "system"]
        chat_msgs = [m for m in api_messages if m["role"] != "system"]

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": chat_msgs,
        }
        if system_msgs:
            kwargs["system"] = "\n\n".join(m["content"] for m in system_msgs)
        if tools:
            kwargs["tools"] = tools
        if think_budget:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": think_budget}

        try:
            response = await client.messages.create(**kwargs)
        except Exception:
            if self._fallback:
                return await self._fallback.chat(messages, tools, think_budget)
            raise

        tool_calls = []
        content = None
        for block in response.content:
            if block.type == "text":
                content = block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCallRequest(
                    id=block.id, name=block.name, arguments=block.input,
                ))

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=TokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            stop_reason=response.stop_reason,
        )

    def get_cache_strategy(self) -> CacheStrategy:
        return CacheStrategy(name="claude_ephemeral", config={"type": "ephemeral"})

    def supports_feature(self, feature: str) -> bool:
        return feature in SUPPORTED_FEATURES

    def transform_system_prompt(self, blocks: list[PromptBlock]) -> list[dict[str, Any]]:
        result = []
        for block in blocks:
            param: dict[str, Any] = {"type": "text", "text": block.content}
            if block.cacheable:
                hints = block.provider_hints.get("claude", {})
                scope = hints.get("scope", "org")
                param["cache_control"] = {"type": "ephemeral", "scope": scope}
            result.append(param)
        return result

    def transform_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        result = []
        for msg in messages:
            entry: dict[str, Any] = {"role": msg.role, "content": msg.content or ""}
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in msg.tool_calls
                ]
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            result.append(entry)
        return result

    @property
    def fallback(self) -> ProviderProtocol | None:
        return self._fallback
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `pytest tests/plugins/test_claude_adapter.py -v`
Expected: All passed

- [ ] **Step 5: 커밋**

```bash
git add src/breadmind/plugins/builtin/__init__.py src/breadmind/plugins/builtin/providers/__init__.py src/breadmind/plugins/builtin/providers/claude_adapter.py tests/plugins/test_claude_adapter.py
git commit -m "feat(providers): add ClaudeAdapter with caching and thinking support"
```

---

### Task 11: Jinja2 프롬프트 빌더 (PromptProtocol 구현)

**Files:**
- Create: `src/breadmind/plugins/builtin/prompt_builder/__init__.py`
- Create: `src/breadmind/plugins/builtin/prompt_builder/jinja_builder.py`
- Test: `tests/plugins/test_jinja_builder.py`

기존 `src/breadmind/prompts/builder.py`를 PromptProtocol 구현체로 이식합니다. 기존 Jinja2 템플릿(`src/breadmind/prompts/`)은 그대로 사용하되, `PromptBlock` 리스트를 출력합니다.

- [ ] **Step 1: 테스트 작성**

```python
# tests/plugins/test_jinja_builder.py
import pytest
from pathlib import Path
from breadmind.core.protocols import PromptBlock, PromptContext
from breadmind.plugins.builtin.prompt_builder.jinja_builder import JinjaPromptBuilder

@pytest.fixture
def builder():
    templates_dir = Path(__file__).resolve().parent.parent.parent / "src" / "breadmind" / "prompts"
    return JinjaPromptBuilder(templates_dir=templates_dir)

def test_build_returns_prompt_blocks(builder: JinjaPromptBuilder):
    ctx = PromptContext(persona_name="TestBot", language="en", provider_model="test-model")
    blocks = builder.build(ctx, provider="claude", persona="professional")
    assert isinstance(blocks, list)
    assert all(isinstance(b, PromptBlock) for b in blocks)
    assert len(blocks) > 0

def test_iron_laws_is_priority_zero(builder: JinjaPromptBuilder):
    ctx = PromptContext()
    blocks = builder.build(ctx, provider="claude")
    iron = [b for b in blocks if b.section == "iron_laws"]
    assert len(iron) == 1
    assert iron[0].priority == 0
    assert iron[0].cacheable is True

def test_identity_block_contains_persona_name(builder: JinjaPromptBuilder):
    ctx = PromptContext(persona_name="MyAgent")
    blocks = builder.build(ctx, provider="claude")
    identity = [b for b in blocks if b.section == "identity"]
    assert len(identity) == 1
    assert "MyAgent" in identity[0].content

def test_dynamic_blocks_not_cacheable(builder: JinjaPromptBuilder):
    ctx = PromptContext(os_info="Linux 6.1", current_date="2026-04-04")
    blocks = builder.build(ctx, provider="claude")
    env_blocks = [b for b in blocks if b.section == "env"]
    assert len(env_blocks) == 1
    assert env_blocks[0].cacheable is False

def test_rebuild_dynamic_returns_only_dynamic(builder: JinjaPromptBuilder):
    ctx = PromptContext(os_info="Linux 6.1", current_date="2026-04-04")
    builder.build(ctx, provider="claude")  # 초기 빌드
    dynamic = builder.rebuild_dynamic(ctx)
    assert all(b.cacheable is False for b in dynamic)

def test_trim_to_budget_removes_high_priority_first(builder: JinjaPromptBuilder):
    ctx = PromptContext()
    blocks = builder.build(ctx, provider="claude")
    trimmed = builder.trim_to_budget(blocks, max_tokens=100)
    priorities = [b.priority for b in trimmed]
    # iron_laws (0) 는 항상 남아있어야 함
    assert 0 in priorities
    assert len(trimmed) <= len(blocks)
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/plugins/test_jinja_builder.py -v`
Expected: FAIL

- [ ] **Step 3: 구현**

```python
# src/breadmind/plugins/builtin/prompt_builder/__init__.py
"""Jinja2 기반 프롬프트 빌더."""

# src/breadmind/plugins/builtin/prompt_builder/jinja_builder.py
from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from breadmind.core.protocols import Message, PromptBlock, PromptContext, CompactResult


class JinjaPromptBuilder:
    """기존 Breadmind PromptBuilder를 PromptProtocol 구현체로 이식.

    Jinja2 템플릿을 렌더링하되, 결과를 PromptBlock 리스트로 반환.
    """

    def __init__(self, templates_dir: Path, token_counter: callable | None = None) -> None:
        self._templates_dir = templates_dir
        self._env = Environment(loader=FileSystemLoader(str(templates_dir)))
        self._count_tokens = token_counter or (lambda text: len(text) // 4)
        self._last_static: list[PromptBlock] = []

    def build(
        self,
        context: PromptContext,
        provider: str = "claude",
        persona: str = "professional",
        role: str | None = None,
    ) -> list[PromptBlock]:
        blocks: list[PromptBlock] = []

        # Iron Laws (불변, cacheable, priority=0)
        iron_laws = self._render_template("behaviors/iron_laws.j2", context)
        blocks.append(PromptBlock(
            section="iron_laws", content=iron_laws,
            cacheable=True, priority=0,
            provider_hints={"claude": {"scope": "global"}},
        ))

        # Identity (cacheable, priority=1)
        identity_vars = self._load_persona_vars(persona)
        role_vars = self._load_role_vars(role) if role else {}
        all_vars = {**self._context_to_dict(context), **identity_vars, **role_vars}
        identity = self._render_provider_template(provider, all_vars)
        blocks.append(PromptBlock(
            section="identity", content=identity,
            cacheable=True, priority=1,
            provider_hints={"claude": {"scope": "org"}},
        ))

        # Behaviors (cacheable, priority=2)
        for tmpl_name in ["proactive", "tool_usage", "delegation", "safety"]:
            tmpl_path = f"behaviors/{tmpl_name}.j2"
            if (self._templates_dir / tmpl_path).exists():
                content = self._render_template(tmpl_path, context)
                blocks.append(PromptBlock(
                    section=f"behavior_{tmpl_name}", content=content,
                    cacheable=True, priority=2,
                ))

        # Role (dynamic, priority=3)
        if role and role_vars:
            blocks.append(PromptBlock(
                section="role", content=role_vars.get("domain_context", ""),
                cacheable=False, priority=3,
            ))

        # Env (dynamic, priority=5)
        env_content = f"OS: {context.os_info}\nDate: {context.current_date}\nModel: {context.provider_model}"
        blocks.append(PromptBlock(section="env", content=env_content, cacheable=False, priority=5))

        # Custom instructions (dynamic, priority=6)
        if context.custom_instructions:
            blocks.append(PromptBlock(
                section="custom", content=context.custom_instructions,
                cacheable=False, priority=6,
            ))

        # Fragments (dynamic, priority=10 — 예산 부족 시 첫 제거)
        for frag in ["os_context", "credential_handling", "interactive_input"]:
            frag_path = f"fragments/{frag}.j2"
            if (self._templates_dir / frag_path).exists():
                content = self._render_template(frag_path, context)
                blocks.append(PromptBlock(
                    section=f"fragment_{frag}", content=content,
                    cacheable=False, priority=10,
                ))

        self._last_static = [b for b in blocks if b.cacheable]
        return blocks

    def rebuild_dynamic(self, context: PromptContext) -> list[PromptBlock]:
        full = self.build(context)
        return [b for b in full if not b.cacheable]

    def trim_to_budget(self, blocks: list[PromptBlock], max_tokens: int) -> list[PromptBlock]:
        total = sum(self._count_tokens(b.content) for b in blocks)
        if total <= max_tokens:
            return blocks

        sorted_blocks = sorted(blocks, key=lambda b: -b.priority)
        result = list(blocks)
        for block in sorted_blocks:
            if block.priority == 0:
                break
            result.remove(block)
            total -= self._count_tokens(block.content)
            if total <= max_tokens:
                break
        return result

    async def compact(self, messages: list[Message], budget_tokens: int) -> CompactResult:
        raise NotImplementedError("Compaction requires LLMCompactor plugin")

    def inject_reminder(self, key: str, content: str) -> Message:
        return Message(
            role="user",
            content=f"<system-reminder>\n# {key}\n{content}\n</system-reminder>",
            is_meta=True,
        )

    def _render_template(self, template_path: str, context: PromptContext) -> str:
        try:
            tmpl = self._env.get_template(template_path)
            return tmpl.render(**self._context_to_dict(context))
        except Exception:
            return ""

    def _render_provider_template(self, provider: str, variables: dict) -> str:
        try:
            tmpl = self._env.get_template(f"providers/{provider}.j2")
            return tmpl.render(**variables)
        except Exception:
            return f"You are {variables.get('persona_name', 'BreadMind')}."

    def _load_persona_vars(self, persona: str) -> dict:
        path = self._templates_dir / "personas" / f"{persona}.j2"
        if not path.exists():
            return {}
        return self._extract_set_vars(path.read_text(encoding="utf-8"))

    def _load_role_vars(self, role: str) -> dict:
        path = self._templates_dir / "roles" / f"{role}.j2"
        if not path.exists():
            return {}
        return self._extract_set_vars(path.read_text(encoding="utf-8"))

    def _extract_set_vars(self, template_text: str) -> dict:
        simple = dict(re.findall(r'\{%\s*set\s+(\w+)\s*=\s*"([^"]*)"\s*%\}', template_text))
        block_pattern = r'\{%\s*set\s+(\w+)\s*%\}(.*?)\{%\s*endset\s*%\}'
        for name, value in re.findall(block_pattern, template_text, re.DOTALL):
            simple[name] = value.strip()
        return simple

    def _context_to_dict(self, context: PromptContext) -> dict:
        return {
            "persona_name": context.persona_name,
            "language": context.language,
            "specialties": context.specialties,
            "os_info": context.os_info,
            "current_date": context.current_date,
            "available_tools": context.available_tools,
            "provider_model": context.provider_model,
            "custom_instructions": context.custom_instructions or "",
        }
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `pytest tests/plugins/test_jinja_builder.py -v`
Expected: All passed

- [ ] **Step 5: 커밋**

```bash
git add src/breadmind/plugins/builtin/prompt_builder/ tests/plugins/test_jinja_builder.py
git commit -m "feat(prompt): add JinjaPromptBuilder implementing PromptProtocol"
```

---

### Task 12: system-reminder 주입기

**Files:**
- Create: `src/breadmind/plugins/builtin/prompt_builder/reminder.py`
- Test: `tests/plugins/test_reminder.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/plugins/test_reminder.py
from unittest.mock import MagicMock
from breadmind.plugins.builtin.prompt_builder.reminder import ReminderInjector

def test_inject_claude_style():
    provider = MagicMock()
    provider.supports_feature.return_value = True
    injector = ReminderInjector()
    msg = injector.inject("memory", "User prefers Korean.", provider)
    assert msg.role == "user"
    assert "<system-reminder>" in msg.content
    assert "# memory" in msg.content
    assert msg.is_meta is True

def test_inject_generic_style():
    provider = MagicMock()
    provider.supports_feature.return_value = False
    injector = ReminderInjector()
    msg = injector.inject("memory", "User prefers Korean.", provider)
    assert msg.role == "system"
    assert "[Context: memory]" in msg.content
    assert msg.is_meta is True
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/plugins/test_reminder.py -v`
Expected: FAIL

- [ ] **Step 3: 구현**

```python
# src/breadmind/plugins/builtin/prompt_builder/reminder.py
from __future__ import annotations

from breadmind.core.protocols import Message, ProviderProtocol


class ReminderInjector:
    """프로바이더에 맞게 대화 중간 컨텍스트를 주입."""

    def inject(self, key: str, content: str, provider: ProviderProtocol) -> Message:
        if provider.supports_feature("system_reminder"):
            return Message(
                role="user",
                content=f"<system-reminder>\n# {key}\n{content}\n</system-reminder>",
                is_meta=True,
            )
        return Message(
            role="system",
            content=f"[Context: {key}]\n{content}",
            is_meta=True,
        )
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `pytest tests/plugins/test_reminder.py -v`
Expected: All passed

- [ ] **Step 5: 커밋**

```bash
git add src/breadmind/plugins/builtin/prompt_builder/reminder.py tests/plugins/test_reminder.py
git commit -m "feat(prompt): add ReminderInjector for provider-aware context injection"
```

---

### Task 13: HybridToolRegistry (ToolProtocol 구현)

**Files:**
- Create: `src/breadmind/plugins/builtin/tools/__init__.py`
- Create: `src/breadmind/plugins/builtin/tools/registry.py`
- Test: `tests/plugins/test_hybrid_registry.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/plugins/test_hybrid_registry.py
import pytest
from breadmind.core.protocols import ToolDefinition, ToolFilter, ToolCall, ToolResult, ExecutionContext
from breadmind.plugins.builtin.tools.registry import HybridToolRegistry

@pytest.fixture
def registry():
    r = HybridToolRegistry()
    r.register(ToolDefinition(name="shell_exec", description="Execute shell", parameters={}))
    r.register(ToolDefinition(name="file_read", description="Read file", parameters={}))
    r.register(ToolDefinition(name="k8s_pods_list", description="List K8s pods", parameters={}))
    r.register(ToolDefinition(name="k8s_pods_get", description="Get K8s pod", parameters={}))
    r.register(ToolDefinition(name="web_search", description="Web search", parameters={}))
    return r

def test_get_all_schemas(registry: HybridToolRegistry):
    schemas = registry.get_schemas()
    assert len(schemas) == 5
    assert all(s.deferred is False for s in schemas)

def test_get_schemas_deferred(registry: HybridToolRegistry):
    f = ToolFilter(use_deferred=True, always_include=["shell_exec", "file_read"])
    schemas = registry.get_schemas(f)
    full = [s for s in schemas if not s.deferred]
    deferred = [s for s in schemas if s.deferred]
    assert len(full) == 2
    assert len(deferred) == 3

def test_get_schemas_intent_filter(registry: HybridToolRegistry):
    f = ToolFilter(intent="k8s", keywords=["pod", "kubernetes"], max_tools=3)
    schemas = registry.get_schemas(f)
    names = [s.name for s in schemas]
    assert "k8s_pods_list" in names
    assert "k8s_pods_get" in names

def test_resolve_deferred(registry: HybridToolRegistry):
    resolved = registry.resolve_deferred(["k8s_pods_list", "web_search"])
    assert len(resolved) == 2
    assert all(s.definition is not None for s in resolved)

def test_get_deferred_tools(registry: HybridToolRegistry):
    names = registry.get_deferred_tools()
    assert len(names) == 5

def test_unregister(registry: HybridToolRegistry):
    registry.unregister("web_search")
    schemas = registry.get_schemas()
    assert len(schemas) == 4
    assert all(s.name != "web_search" for s in schemas)

def test_unregister_nonexistent(registry: HybridToolRegistry):
    registry.unregister("nonexistent")  # should not raise
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/plugins/test_hybrid_registry.py -v`
Expected: FAIL

- [ ] **Step 3: 구현**

```python
# src/breadmind/plugins/builtin/tools/__init__.py
"""도구 시스템."""

# src/breadmind/plugins/builtin/tools/registry.py
from __future__ import annotations

from breadmind.core.protocols import (
    ToolCall,
    ToolDefinition,
    ToolFilter,
    ToolResult,
    ToolSchema,
    ExecutionContext,
)


class HybridToolRegistry:
    """의도 기반 + deferred 하이브리드 도구 레지스트리."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._executors: dict[str, callable] = {}

    def register(self, tool: ToolDefinition, executor: callable | None = None) -> None:
        self._tools[tool.name] = tool
        if executor:
            self._executors[tool.name] = executor

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)
        self._executors.pop(name, None)

    def get_schemas(self, filter: ToolFilter | None = None) -> list[ToolSchema]:
        if filter is None:
            return [
                ToolSchema(name=t.name, deferred=False, definition=t)
                for t in self._tools.values()
            ]

        if filter.use_deferred:
            return self._get_deferred_schemas(filter)
        if filter.intent or filter.keywords:
            return self._get_intent_filtered(filter)
        return [
            ToolSchema(name=t.name, deferred=False, definition=t)
            for t in self._tools.values()
        ]

    def get_deferred_tools(self) -> list[str]:
        return list(self._tools.keys())

    def resolve_deferred(self, names: list[str]) -> list[ToolSchema]:
        result = []
        for name in names:
            if name in self._tools:
                result.append(ToolSchema(
                    name=name, deferred=False, definition=self._tools[name],
                ))
        return result

    async def execute(self, call: ToolCall, ctx: ExecutionContext) -> ToolResult:
        executor = self._executors.get(call.name)
        if not executor:
            return ToolResult(success=False, output="", error=f"No executor for tool '{call.name}'")
        try:
            output = await executor(**call.arguments)
            return ToolResult(success=True, output=str(output))
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    def _get_deferred_schemas(self, filter: ToolFilter) -> list[ToolSchema]:
        always = set(filter.always_include)
        result = []
        for name, tool in self._tools.items():
            if name in always:
                result.append(ToolSchema(name=name, deferred=False, definition=tool))
            else:
                result.append(ToolSchema(name=name, deferred=True))
        return result

    def _get_intent_filtered(self, filter: ToolFilter) -> list[ToolSchema]:
        scored: list[tuple[float, str, ToolDefinition]] = []
        keywords = set(filter.keywords or [])
        intent = (filter.intent or "").lower()

        for name, tool in self._tools.items():
            score = 0.0
            name_lower = name.lower()
            desc_lower = tool.description.lower()

            if intent and intent in name_lower:
                score += 10.0
            for kw in keywords:
                if kw.lower() in name_lower or kw.lower() in desc_lower:
                    score += 5.0

            scored.append((score, name, tool))

        scored.sort(key=lambda x: -x[0])
        max_tools = filter.max_tools or len(scored)
        return [
            ToolSchema(name=name, deferred=False, definition=tool)
            for _, name, tool in scored[:max_tools]
            if True  # 모든 도구 포함 (점수순 정렬)
        ]
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `pytest tests/plugins/test_hybrid_registry.py -v`
Expected: All passed

- [ ] **Step 5: 커밋**

```bash
git add src/breadmind/plugins/builtin/tools/ tests/plugins/test_hybrid_registry.py
git commit -m "feat(tools): add HybridToolRegistry with intent + deferred support"
```

---

### Task 14: SafetyGuard + Autonomy Level

**Files:**
- Create: `src/breadmind/plugins/builtin/safety/__init__.py`
- Create: `src/breadmind/plugins/builtin/safety/guard.py`
- Test: `tests/plugins/test_safety_guard.py`

기존 `src/breadmind/core/safety.py`를 이식하되, autonomy level을 추가합니다.

- [ ] **Step 1: 테스트 작성**

```python
# tests/plugins/test_safety_guard.py
import pytest
from breadmind.plugins.builtin.safety.guard import SafetyGuard, SafetyVerdict

@pytest.fixture
def guard_auto():
    return SafetyGuard(autonomy="auto", blocked_patterns=["rm -rf /", "mkfs"])

@pytest.fixture
def guard_destructive():
    return SafetyGuard(autonomy="confirm-destructive", blocked_patterns=["rm -rf /"])

@pytest.fixture
def guard_all():
    return SafetyGuard(autonomy="confirm-all")

def test_auto_allows_everything(guard_auto: SafetyGuard):
    v = guard_auto.check("shell_exec", {"command": "ls -la"})
    assert v.allowed is True
    assert v.needs_approval is False

def test_auto_blocks_blacklist(guard_auto: SafetyGuard):
    v = guard_auto.check("shell_exec", {"command": "rm -rf /"})
    assert v.allowed is False
    assert "blocked" in v.reason.lower()

def test_destructive_approves_safe(guard_destructive: SafetyGuard):
    v = guard_destructive.check("file_read", {"path": "/etc/hosts"})
    assert v.allowed is True
    assert v.needs_approval is False

def test_destructive_requires_approval_for_delete(guard_destructive: SafetyGuard):
    v = guard_destructive.check("shell_exec", {"command": "kubectl delete pod nginx"})
    assert v.needs_approval is True

def test_confirm_all_requires_approval_always(guard_all: SafetyGuard):
    v = guard_all.check("file_read", {"path": "/tmp/test"})
    assert v.needs_approval is True

def test_blocked_patterns_override_all_levels():
    guard = SafetyGuard(autonomy="auto", blocked_patterns=["dd if="])
    v = guard.check("shell_exec", {"command": "dd if=/dev/zero of=/dev/sda"})
    assert v.allowed is False

def test_custom_approve_required():
    guard = SafetyGuard(autonomy="confirm-destructive", approve_required=["web_search"])
    v = guard.check("web_search", {"query": "test"})
    assert v.needs_approval is True
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/plugins/test_safety_guard.py -v`
Expected: FAIL

- [ ] **Step 3: 구현**

```python
# src/breadmind/plugins/builtin/safety/__init__.py
"""안전장치."""

# src/breadmind/plugins/builtin/safety/guard.py
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

DESTRUCTIVE_PATTERNS = [
    r"\bdelete\b", r"\bremove\b", r"\bdrop\b", r"\bkill\b",
    r"\brestart\b", r"\breboot\b", r"\bstop\b", r"\bdestroy\b",
    r"\brm\s", r"\bshutdown\b",
]

DESTRUCTIVE_TOOLS = frozenset({
    "k8s_pods_delete", "proxmox_delete_vm", "proxmox_delete_lxc",
    "proxmox_stop_vm", "proxmox_reboot_vm", "proxmox_shutdown_vm",
})


@dataclass
class SafetyVerdict:
    """안전 검사 결과."""
    allowed: bool
    needs_approval: bool = False
    reason: str = ""


class SafetyGuard:
    """autonomy level 기반 안전장치."""

    def __init__(
        self,
        autonomy: str = "confirm-destructive",
        blocked_patterns: list[str] | None = None,
        approve_required: list[str] | None = None,
    ) -> None:
        self._autonomy = autonomy
        self._blocked = [re.compile(re.escape(p)) for p in (blocked_patterns or [])]
        self._approve_required = set(approve_required or [])

    def check(self, tool_name: str, arguments: dict[str, Any]) -> SafetyVerdict:
        # 1. 블랙리스트 — 모든 레벨에서 무조건 차단
        args_str = str(arguments)
        for pattern in self._blocked:
            if pattern.search(args_str):
                return SafetyVerdict(allowed=False, reason=f"Blocked pattern matched: {pattern.pattern}")

        # 2. autonomy 레벨별 판단
        if self._autonomy == "auto":
            return SafetyVerdict(allowed=True)

        if self._autonomy == "confirm-all":
            return SafetyVerdict(allowed=True, needs_approval=True, reason="confirm-all mode")

        # confirm-destructive / confirm-unsafe
        if tool_name in self._approve_required:
            return SafetyVerdict(allowed=True, needs_approval=True, reason=f"Tool '{tool_name}' requires approval")

        if self._is_destructive(tool_name, arguments):
            return SafetyVerdict(allowed=True, needs_approval=True, reason="Destructive action detected")

        if self._autonomy == "confirm-unsafe" and self._is_external(tool_name):
            return SafetyVerdict(allowed=True, needs_approval=True, reason="External action in confirm-unsafe mode")

        return SafetyVerdict(allowed=True)

    def _is_destructive(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        if tool_name in DESTRUCTIVE_TOOLS:
            return True
        args_str = str(arguments).lower()
        return any(re.search(p, args_str) for p in DESTRUCTIVE_PATTERNS)

    def _is_external(self, tool_name: str) -> bool:
        return tool_name in {"web_search", "web_fetch", "shell_exec", "file_write"}
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `pytest tests/plugins/test_safety_guard.py -v`
Expected: All passed

- [ ] **Step 5: 커밋**

```bash
git add src/breadmind/plugins/builtin/safety/ tests/plugins/test_safety_guard.py
git commit -m "feat(safety): add SafetyGuard with 4-level autonomy"
```

---

### Task 15: 기본 에이전트 루프 (AgentProtocol 구현)

**Files:**
- Create: `src/breadmind/plugins/builtin/agent_loop/__init__.py`
- Create: `src/breadmind/plugins/builtin/agent_loop/message_loop.py`
- Test: `tests/plugins/test_message_loop.py`

핵심 에이전트 루프: system prompt 빌드 → LLM 호출 → 도구 실행 → 반복.

- [ ] **Step 1: 테스트 작성**

```python
# tests/plugins/test_message_loop.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.core.protocols import (
    Message, LLMResponse, TokenUsage, AgentContext, AgentResponse,
    PromptBlock, PromptContext, ToolCallRequest, ToolCall, ToolResult,
    ExecutionContext,
)
from breadmind.plugins.builtin.agent_loop.message_loop import MessageLoopAgent

@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    provider.supports_feature.return_value = False
    provider.transform_system_prompt.side_effect = lambda blocks: blocks
    provider.transform_messages.side_effect = lambda msgs: msgs
    provider.fallback = None
    return provider

@pytest.fixture
def mock_prompt_builder():
    builder = MagicMock()
    builder.build.return_value = [
        PromptBlock(section="iron_laws", content="Never guess.", cacheable=True, priority=0),
    ]
    builder.inject_reminder.side_effect = lambda k, c: Message(role="user", content=c, is_meta=True)
    return builder

@pytest.fixture
def mock_tool_registry():
    registry = MagicMock()
    registry.get_schemas.return_value = []
    registry.execute = AsyncMock(return_value=ToolResult(success=True, output="done"))
    return registry

@pytest.fixture
def mock_safety():
    from breadmind.plugins.builtin.safety.guard import SafetyVerdict
    guard = MagicMock()
    guard.check.return_value = SafetyVerdict(allowed=True)
    return guard

@pytest.fixture
def agent(mock_provider, mock_prompt_builder, mock_tool_registry, mock_safety):
    return MessageLoopAgent(
        provider=mock_provider,
        prompt_builder=mock_prompt_builder,
        tool_registry=mock_tool_registry,
        safety_guard=mock_safety,
        max_turns=5,
    )

@pytest.mark.asyncio
async def test_simple_text_response(agent, mock_provider):
    mock_provider.chat.return_value = LLMResponse(
        content="Hello!", tool_calls=[], usage=TokenUsage(10, 5), stop_reason="end_turn",
    )
    ctx = AgentContext(user="test", channel="cli", session_id="s1")
    resp = await agent.handle_message("hi", ctx)
    assert resp.content == "Hello!"
    assert resp.tool_calls_count == 0

@pytest.mark.asyncio
async def test_tool_call_then_response(agent, mock_provider, mock_tool_registry):
    mock_provider.chat.side_effect = [
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="tc1", name="shell_exec", arguments={"command": "ls"})],
            usage=TokenUsage(10, 5), stop_reason="tool_use",
        ),
        LLMResponse(
            content="Files listed.", tool_calls=[], usage=TokenUsage(20, 10), stop_reason="end_turn",
        ),
    ]
    ctx = AgentContext(user="test", channel="cli", session_id="s1")
    resp = await agent.handle_message("list files", ctx)
    assert resp.content == "Files listed."
    assert resp.tool_calls_count == 1
    mock_tool_registry.execute.assert_called_once()

@pytest.mark.asyncio
async def test_max_turns_limit(agent, mock_provider):
    mock_provider.chat.return_value = LLMResponse(
        content=None,
        tool_calls=[ToolCallRequest(id="tc1", name="shell_exec", arguments={})],
        usage=TokenUsage(10, 5), stop_reason="tool_use",
    )
    ctx = AgentContext(user="test", channel="cli", session_id="s1")
    resp = await agent.handle_message("loop", ctx)
    assert mock_provider.chat.call_count == 5  # max_turns
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/plugins/test_message_loop.py -v`
Expected: FAIL

- [ ] **Step 3: 구현**

```python
# src/breadmind/plugins/builtin/agent_loop/__init__.py
"""에이전트 루프."""

# src/breadmind/plugins/builtin/agent_loop/message_loop.py
from __future__ import annotations

import uuid
from typing import Any

from breadmind.core.protocols import (
    AgentContext,
    AgentProtocol,
    AgentResponse,
    ExecutionContext,
    LLMResponse,
    Message,
    PromptBlock,
    PromptContext,
    ProviderProtocol,
    ToolCall,
    ToolCallRequest,
)
from breadmind.plugins.builtin.safety.guard import SafetyGuard


class MessageLoopAgent:
    """기본 메시지 루프 에이전트. AgentProtocol 구현."""

    def __init__(
        self,
        provider: ProviderProtocol,
        prompt_builder: Any,
        tool_registry: Any,
        safety_guard: SafetyGuard,
        max_turns: int = 10,
        memory: Any | None = None,
        prompt_context: PromptContext | None = None,
    ) -> None:
        self._provider = provider
        self._prompt_builder = prompt_builder
        self._tool_registry = tool_registry
        self._safety = safety_guard
        self._max_turns = max_turns
        self._memory = memory
        self._prompt_context = prompt_context or PromptContext()
        self._agent_id = f"agent_{uuid.uuid4().hex[:8]}"

    @property
    def agent_id(self) -> str:
        return self._agent_id

    async def handle_message(self, message: str, ctx: AgentContext) -> AgentResponse:
        # 시스템 프롬프트 빌드
        blocks = self._prompt_builder.build(self._prompt_context)
        system_content = "\n\n".join(b.content for b in blocks if b.content)

        # 메시지 구성
        messages: list[Message] = [
            Message(role="system", content=system_content),
            Message(role="user", content=message),
        ]

        # 도구 스키마
        tool_schemas = self._tool_registry.get_schemas()
        tools = [
            {"name": s.name, "description": s.definition.description, "input_schema": s.definition.parameters}
            for s in tool_schemas if s.definition
        ] or None

        total_tool_calls = 0
        total_tokens = 0

        for _ in range(self._max_turns):
            response: LLMResponse = await self._provider.chat(messages, tools)
            total_tokens += response.usage.total_tokens

            if not response.has_tool_calls:
                return AgentResponse(
                    content=response.content or "",
                    tool_calls_count=total_tool_calls,
                    tokens_used=total_tokens,
                )

            # 도구 호출 처리
            if response.content:
                messages.append(Message(role="assistant", content=response.content))

            assistant_msg = Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                total_tool_calls += 1
                exec_ctx = ExecutionContext(
                    user=ctx.user, channel=ctx.channel,
                    session_id=ctx.session_id, autonomy="auto",
                )

                verdict = self._safety.check(tc.name, tc.arguments)
                if not verdict.allowed:
                    messages.append(Message(
                        role="tool", content=f"Blocked: {verdict.reason}",
                        tool_call_id=tc.id,
                    ))
                    continue

                tool_call = ToolCall(id=tc.id, name=tc.name, arguments=tc.arguments)
                result = await self._tool_registry.execute(tool_call, exec_ctx)
                messages.append(Message(
                    role="tool", content=result.output if result.success else f"Error: {result.error}",
                    tool_call_id=tc.id,
                ))

        # max_turns 도달
        return AgentResponse(
            content="Max turns reached.",
            tool_calls_count=total_tool_calls,
            tokens_used=total_tokens,
        )

    async def spawn(self, prompt: str, tools: list[str] | None = None, isolation: str | None = None) -> AgentProtocol:
        raise NotImplementedError("Spawner plugin required")

    async def send_message(self, target: str, message: str) -> str:
        raise NotImplementedError("Send message not implemented in base loop")

    def set_role(self, role: str) -> None:
        self._prompt_context.role = role
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `pytest tests/plugins/test_message_loop.py -v`
Expected: All passed

- [ ] **Step 5: 커밋**

```bash
git add src/breadmind/plugins/builtin/agent_loop/ tests/plugins/test_message_loop.py
git commit -m "feat(agent): add MessageLoopAgent implementing AgentProtocol"
```

---

## Phase 3: 기능 (메모리, 압축, dream)

### Task 16: WorkingMemory (MemoryProtocol 부분 구현)

기존 `src/breadmind/memory/working.py`를 이식하되, MemoryProtocol의 working_* 메서드를 구현합니다.

**Files:**
- Create: `src/breadmind/plugins/builtin/memory/__init__.py`
- Create: `src/breadmind/plugins/builtin/memory/working_memory.py`
- Test: `tests/plugins/test_working_memory.py`

> 구현 코드는 기존 `src/breadmind/memory/working.py`의 ConversationSession, WorkingMemory 로직을 이식. MemoryProtocol.working_get/put/compress를 구현하고, compress에서 LLM 기반 압축을 사용.

이하 Phase 3~5 태스크는 동일 패턴(테스트 → 실패 확인 → 구현 → 통과 → 커밋)으로 진행합니다.

---

### Task 17: LLM 기반 컨텍스트 압축기

**Files:**
- Create: `src/breadmind/plugins/builtin/prompt_builder/compactor.py`
- Test: `tests/plugins/test_compactor.py`

> Claude Code의 `compact.ts` 패턴 이식: 이미지/문서 마커 교체 → 라운드별 그룹화 → LLM 요약 → 경계 메시지 + 최근 보존.

---

### Task 18: Dreamer (메모리 정리)

**Files:**
- Create: `src/breadmind/plugins/builtin/memory/dreamer.py`
- Test: `tests/plugins/test_dreamer.py`

> Claude Code autoDream 4단계 패턴: Orient → Gather → Consolidate → Prune. 이벤트 버스에서 `session.ended` 수신 시 비동기 실행.

---

### Task 19: EpisodicMemory + SemanticMemory 이식

**Files:**
- Create: `src/breadmind/plugins/builtin/memory/episodic_memory.py`
- Create: `src/breadmind/plugins/builtin/memory/semantic_memory.py`
- Test: `tests/plugins/test_episodic_memory.py`

> 기존 `src/breadmind/memory/episodic.py`, `src/breadmind/memory/semantic.py` 이식.

---

### Task 20: ContextBuilder + SmartRetriever 이식

**Files:**
- Create: `src/breadmind/plugins/builtin/memory/context_builder.py`
- Create: `src/breadmind/plugins/builtin/memory/smart_retriever.py`

> 기존 `src/breadmind/memory/context_builder.py`, `src/breadmind/core/smart_retriever.py` 이식. `build_context_block()` 구현 — 검색 결과를 PromptBlock으로 패키징.

---

## Phase 4: 런타임 + SDK

### Task 21: SDK Agent 클래스

**Files:**
- Create: `src/breadmind/sdk/__init__.py`
- Create: `src/breadmind/sdk/agent.py`
- Test: `tests/sdk/test_agent_sdk.py`

> 5줄 최소 에이전트부터 풀 커스텀까지. `Agent(name, config, prompt, memory, tools, safety, plugins)`. `run()`, `serve(runtime=)` 메서드.

---

### Task 22: YAML DSL 로더

**Files:**
- Create: `src/breadmind/dsl/__init__.py`
- Create: `src/breadmind/dsl/yaml_loader.py`
- Test: `tests/sdk/test_yaml_loader.py`

> YAML 파싱 → `Agent` 인스턴스 생성. `Agent.from_yaml(path)` 정적 메서드.

---

### Task 23: CLI 런타임

**Files:**
- Create: `src/breadmind/plugins/builtin/runtimes/__init__.py`
- Create: `src/breadmind/plugins/builtin/runtimes/cli_runtime.py`
- Test: `tests/plugins/test_cli_runtime.py`

> `RuntimeProtocol` 구현: stdin/stdout 기반 대화 루프. `breadmind run agent.yaml --runtime cli`.

---

### Task 24: 서버 런타임

**Files:**
- Create: `src/breadmind/plugins/builtin/runtimes/server_runtime.py`
- Test: `tests/plugins/test_server_runtime.py`

> `RuntimeProtocol` 구현: FastAPI + WebSocket. 기존 `src/breadmind/web/routes/` 이식.

---

### Task 25: 서브에이전트 Spawner

**Files:**
- Create: `src/breadmind/plugins/builtin/agent_loop/spawner.py`
- Test: `tests/plugins/test_spawner.py`

> `AgentProtocol.spawn()` 구현 + SwarmPlan 기반 선언적 실행. depth 제한.

---

## Phase 5: 도메인 마이그레이션

### Task 26: 인프라 도메인 플러그인

**Files:**
- Create: `src/breadmind/plugins/domains/infra/`
- 기존 `src/breadmind/plugins/builtin/network/` 코드를 도메인 플러그인으로 이동

> k8s_tools, proxmox_tools, openwrt_tools, roles/*.j2, skills/*.yaml

---

### Task 27: 진입점 전환

**Files:**
- Modify: `src/breadmind/cli/`

> 기존 `python -m breadmind` 진입점을 새 SDK 기반으로 전환. `breadmind run`, `breadmind create` 명령 추가.

---

### Task 28: 통합 테스트

**Files:**
- Create: `tests/integration/test_single_turn.py`
- Create: `tests/integration/test_multi_turn.py`
- Create: `tests/integration/test_sub_agent.py`

> Phase 검증 기준에 맞춰 end-to-end 테스트:
> - 단일 턴 대화 (시스템 프롬프트 → LLM → 응답)
> - 멀티턴 + 도구 호출
> - 서브에이전트 spawn + swarm

---

### Task 29: 기존 코드 정리 + main 머지

- [ ] 모든 Phase 검증 기준 통과 확인
- [ ] 기존 `src/breadmind/core/agent.py`, `src/breadmind/llm/`, `src/breadmind/memory/` 등 이전 코드 삭제
- [ ] feature/framework-core → main 머지
- [ ] 기존 코드 아카이브 태그 생성
