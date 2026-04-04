# v1→v2 빅뱅 마이그레이션 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** v2 코드의 `v2_` 접두사와 `v2_builtin/` 분리를 제거하고, v1과 통합하여 단일 코드베이스로 만든다.

**Architecture:** 파일 이동(git mv) + import 경로 일괄 변경. EventBus는 v2로 교체하되 v1 호환 래퍼(EventType, Event, get_event_bus, publish_fire_and_forget) 포함. ContainerExecutor는 sandbox.py로 이동.

**Tech Stack:** Python 3.12+, pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-04-04-bigbang-migration-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Move | `core/container.py` → `core/sandbox.py` | ContainerExecutor (Docker 샌드박스) |
| Replace | `core/events.py` | v2 EventBus + v1 호환 래퍼 |
| Move | `core/v2_container.py` → `core/container.py` | DI Container |
| Move | `core/v2_plugin.py` → `core/plugin.py` | PluginLoader |
| Delete | `core/v2_events.py` | v2 EventBus (events.py에 통합) |
| Move | `plugins/v2_builtin/*` → `plugins/builtin/*` | v2 플러그인 합치기 |
| Modify | 6 v1 event 소비자 | EventType/Event → v2 호환 래퍼 사용 유지 |
| Modify | 2 v1 container 소비자 | container → sandbox import |
| Modify | ~8 v2 src import | v2_ 접두사 제거 |
| Modify | ~21 test import | v2_ 접두사 제거 |

---

### Task 1: ContainerExecutor를 sandbox.py로 이동

**Files:**
- Move: `src/breadmind/core/container.py` → `src/breadmind/core/sandbox.py`
- Modify: `src/breadmind/tools/builtin.py:195`
- Modify: `src/breadmind/plugins/builtin/core_tools/plugin.py:258`

- [ ] **Step 1: git mv로 파일 이동**

```bash
cd D:/Projects/breadmind
git mv src/breadmind/core/container.py src/breadmind/core/sandbox.py
```

- [ ] **Step 2: builtin.py의 import 변경**

`src/breadmind/tools/builtin.py:195` 변경:
```python
# Old:
from breadmind.core.container import ContainerExecutor
# New:
from breadmind.core.sandbox import ContainerExecutor
```

- [ ] **Step 3: core_tools/plugin.py의 import 변경**

`src/breadmind/plugins/builtin/core_tools/plugin.py:258` 변경:
```python
# Old:
from breadmind.core.container import ContainerExecutor
# New:
from breadmind.core.sandbox import ContainerExecutor
```

- [ ] **Step 4: 테스트 실행**

Run: `python -m pytest tests/test_container.py tests/test_builtin_tools.py -v --tb=short 2>&1 | tail -20`

- [ ] **Step 5: 커밋**

```bash
git add -A
git commit -m "refactor: move ContainerExecutor to core/sandbox.py"
```

---

### Task 2: v2 Container를 core/container.py로 이동

**Files:**
- Move: `src/breadmind/core/v2_container.py` → `src/breadmind/core/container.py`
- Modify: `src/breadmind/core/v2_plugin.py:7` (import 변경)
- Modify: `tests/core/test_v2_container.py:3` (import 변경)

- [ ] **Step 1: git mv**

```bash
git mv src/breadmind/core/v2_container.py src/breadmind/core/container.py
```

- [ ] **Step 2: v2_plugin.py import 변경**

`src/breadmind/core/v2_plugin.py:7`:
```python
# Old:
from breadmind.core.v2_container import Container
# New:
from breadmind.core.container import Container
```

- [ ] **Step 3: test import 변경**

`tests/core/test_v2_container.py:3`:
```python
# Old:
from breadmind.core.v2_container import Container
# New:
from breadmind.core.container import Container
```

- [ ] **Step 4: 테스트**

Run: `python -m pytest tests/core/test_v2_container.py -v`

- [ ] **Step 5: 커밋**

```bash
git add -A
git commit -m "refactor: move v2 DI Container to core/container.py"
```

---

### Task 3: EventBus 통합 — v2로 교체 + v1 호환 래퍼

**Files:**
- Replace: `src/breadmind/core/events.py` (v1 삭제, v2 + 호환 래퍼)
- Delete: `src/breadmind/core/v2_events.py`
- Modify: `src/breadmind/core/v2_plugin.py:8` (import 변경)
- Modify: `tests/core/test_v2_events.py:2` (import 변경)

- [ ] **Step 1: events.py를 v2 EventBus + v1 호환 래퍼로 교체**

`src/breadmind/core/events.py` 전체를 다음으로 교체:

```python
"""Central event bus for BreadMind — v2 string-based + v1 compatibility layer."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


# ── v2 Core EventBus ──────────────────────────────────────────────────

class EventBus:
    """v2 타입드 이벤트 버스 + v1 호환."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable]] = defaultdict(list)

    # v2 API
    def on(self, event: str, handler: Callable) -> None:
        self._listeners[event].append(handler)

    def off(self, event: str, handler: Callable) -> None:
        listeners = self._listeners.get(event, [])
        if handler in listeners:
            listeners.remove(handler)

    def emit(self, event: str, data: Any = None) -> None:
        for handler in self._listeners.get(event, []):
            if asyncio.iscoroutinefunction(handler):
                continue
            handler(data)

    async def async_emit(self, event: str, data: Any = None) -> None:
        for handler in self._listeners.get(event, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as e:
                logger.error("Event handler error for %s: %s", event, e)

    # v1 compatibility API
    def subscribe(self, event_type: EventType | str, callback: Callable) -> None:
        key = event_type.value if isinstance(event_type, EventType) else event_type
        self.on(key, callback)

    def subscribe_all(self, callback: Callable) -> None:
        self.on("*", callback)

    def unsubscribe(self, event_type: EventType | str, callback: Callable) -> None:
        key = event_type.value if isinstance(event_type, EventType) else event_type
        self.off(key, callback)

    def unsubscribe_all(self, callback: Callable) -> None:
        self.off("*", callback)

    async def publish(self, event: Event) -> None:
        key = event.type.value if isinstance(event.type, EventType) else str(event.type)
        await self.async_emit(key, event.data)
        # Global subscribers
        for handler in self._listeners.get("*", []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event.data)
                else:
                    handler(event.data)
            except Exception as e:
                logger.error("Global event handler error: %s", e)

    async def publish_fire_and_forget(self, event: Event) -> None:
        asyncio.create_task(self.publish(event))


# ── v1 Compatibility Types ─────────────────────────────────────────────

class EventType(str, Enum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    INTENT_CLASSIFIED = "intent_classified"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    TOOL_APPROVED = "tool_approved"
    TOOL_DENIED = "tool_denied"
    ORCHESTRATOR_START = "orchestrator_start"
    ORCHESTRATOR_REPLAN = "orchestrator_replan"
    ORCHESTRATOR_END = "orchestrator_end"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_END = "subagent_end"
    SUBAGENT_FAILED = "subagent_failed"
    DAG_BATCH_START = "dag_batch_start"
    DAG_BATCH_END = "dag_batch_end"
    MESSENGER_CONNECTED = "messenger_connected"
    MESSENGER_DISCONNECTED = "messenger_disconnected"
    MESSENGER_RECONNECTED = "messenger_reconnected"
    MESSENGER_FAILED = "messenger_failed"
    MESSENGER_ERROR = "messenger_error"
    PROVIDER_CHANGED = "provider_changed"
    CONFIG_UPDATED = "config_updated"
    MONITORING_ALERT = "monitoring_alert"
    MEMORY_SAVED = "memory_saved"
    MEMORY_PROMOTED = "memory_promoted"


@dataclass
class Event:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""


# ── Singleton ──────────────────────────────────────────────────────────

_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
```

- [ ] **Step 2: v2_events.py 삭제**

```bash
git rm src/breadmind/core/v2_events.py
```

- [ ] **Step 3: v2_plugin.py import 변경**

`src/breadmind/core/v2_plugin.py:8`:
```python
# Old:
from breadmind.core.v2_events import EventBus
# New:
from breadmind.core.events import EventBus
```

- [ ] **Step 4: test import 변경**

`tests/core/test_v2_events.py:2`:
```python
# Old:
from breadmind.core.v2_events import EventBus
# New:
from breadmind.core.events import EventBus
```

- [ ] **Step 5: 테스트**

Run: `python -m pytest tests/core/test_v2_events.py tests/test_agent.py -v --tb=short 2>&1 | tail -20`

- [ ] **Step 6: 커밋**

```bash
git add -A
git commit -m "refactor: unify EventBus — v2 core + v1 compatibility layer"
```

---

### Task 4: v2_plugin.py를 core/plugin.py로 이동

**Files:**
- Move: `src/breadmind/core/v2_plugin.py` → `src/breadmind/core/v2_plugin_new.py` (임시, 기존 plugins/ 충돌 방지)
- Modify: imports

주의: 기존 `plugins/` 디렉토리에 `manifest.py`, `loader.py`, `registry.py`가 있지만 `core/plugin.py`는 없으므로 충돌 없음.

- [ ] **Step 1: git mv**

```bash
git mv src/breadmind/core/v2_plugin.py src/breadmind/core/plugin.py
```

- [ ] **Step 2: infra plugin import 변경**

`src/breadmind/plugins/v2_builtin/domains/infra/plugin.py:4`:
```python
# Old:
from breadmind.core.v2_plugin import PluginManifest
# New:
from breadmind.core.plugin import PluginManifest
```

- [ ] **Step 3: test import 변경**

`tests/core/test_v2_plugin.py:2`:
```python
# Old:
from breadmind.core.v2_plugin import PluginLoader, PluginManifest
# New:
from breadmind.core.plugin import PluginLoader, PluginManifest
```

- [ ] **Step 4: 테스트**

Run: `python -m pytest tests/core/test_v2_plugin.py -v`

- [ ] **Step 5: 커밋**

```bash
git add -A
git commit -m "refactor: move PluginLoader to core/plugin.py"
```

---

### Task 5: plugins/v2_builtin/ → plugins/builtin/ 합치기

**Files:**
- Move: `src/breadmind/plugins/v2_builtin/*` → `src/breadmind/plugins/builtin/`
- Delete: `src/breadmind/plugins/v2_builtin/`

v2_builtin/ 하위 디렉토리(agent_loop, domains, memory, prompt_builder, providers, runtimes, safety, tools)는 v1 builtin/ 하위와 이름이 겹치지 않으므로 안전하게 이동 가능.

- [ ] **Step 1: 각 서브디렉토리를 이동**

```bash
cd D:/Projects/breadmind
# 각 v2 디렉토리를 builtin/으로 이동
git mv src/breadmind/plugins/v2_builtin/agent_loop src/breadmind/plugins/builtin/agent_loop
git mv src/breadmind/plugins/v2_builtin/domains src/breadmind/plugins/builtin/domains
git mv src/breadmind/plugins/v2_builtin/memory src/breadmind/plugins/builtin/memory
git mv src/breadmind/plugins/v2_builtin/prompt_builder src/breadmind/plugins/builtin/prompt_builder
git mv src/breadmind/plugins/v2_builtin/providers src/breadmind/plugins/builtin/providers
git mv src/breadmind/plugins/v2_builtin/runtimes src/breadmind/plugins/builtin/runtimes
git mv src/breadmind/plugins/v2_builtin/safety src/breadmind/plugins/builtin/safety
git mv src/breadmind/plugins/v2_builtin/tools src/breadmind/plugins/builtin/tools
# v2_builtin 디렉토리 삭제 (빈 __init__.py만 남음)
git rm src/breadmind/plugins/v2_builtin/__init__.py
```

- [ ] **Step 2: 커밋 (import 변경 전에 파일 이동만 먼저)**

```bash
git add -A
git commit -m "refactor: move v2_builtin plugins into plugins/builtin"
```

---

### Task 6: v2_builtin → builtin import 일괄 변경 (src/)

**Files:** 약 8개 src 파일

모든 `breadmind.plugins.v2_builtin` → `breadmind.plugins.builtin` 으로 변경.

- [ ] **Step 1: 일괄 치환**

대상 파일과 변경:

`src/breadmind/sdk/agent.py` (6곳):
```python
# All occurrences:
# Old: breadmind.plugins.v2_builtin
# New: breadmind.plugins.builtin
```

`src/breadmind/plugins/builtin/agent_loop/message_loop.py` (1곳):
```python
# Old: from breadmind.plugins.v2_builtin.safety.guard import SafetyGuard
# New: from breadmind.plugins.builtin.safety.guard import SafetyGuard
```

`src/breadmind/plugins/builtin/domains/infra/plugin.py` (2곳):
```python
# Old: from breadmind.plugins.v2_builtin.domains.infra.tools import ALL_INFRA_TOOLS
# New: from breadmind.plugins.builtin.domains.infra.tools import ALL_INFRA_TOOLS
# Old: from breadmind.plugins.v2_builtin.domains.infra.roles import INFRA_ROLES
# New: from breadmind.plugins.builtin.domains.infra.roles import INFRA_ROLES
```

`src/breadmind/plugins/builtin/runtimes/__init__.py` (1곳):
```python
# Old: from breadmind.plugins.v2_builtin.runtimes.cli_runtime import CLIRuntime
# New: from breadmind.plugins.builtin.runtimes.cli_runtime import CLIRuntime
```

`src/breadmind/plugins/builtin/memory/context_builder.py` (1곳):
```python
# Old: from breadmind.plugins.v2_builtin.memory.smart_retriever import SmartRetriever
# New: from breadmind.plugins.builtin.memory.smart_retriever import SmartRetriever
```

- [ ] **Step 2: 커밋**

```bash
git add -A
git commit -m "refactor: update src imports from v2_builtin to builtin"
```

---

### Task 7: 테스트 파일 import 일괄 변경

**Files:** 약 21개 테스트 파일

모든 테스트 파일에서 `v2_builtin` → `builtin`, `v2_events` → `events`, `v2_container` → `container`, `v2_plugin` → `plugin` 변경.

- [ ] **Step 1: 테스트 파일 import 일괄 치환**

모든 `tests/` 파일에서:
- `breadmind.plugins.v2_builtin` → `breadmind.plugins.builtin`
- `breadmind.core.v2_plugin` → `breadmind.core.plugin`
- `breadmind.core.v2_container` → `breadmind.core.container`
- `breadmind.core.v2_events` → `breadmind.core.events`

대상 파일 목록 (21개):
- `tests/core/test_v2_events.py`
- `tests/core/test_v2_container.py`
- `tests/core/test_v2_plugin.py`
- `tests/plugins/test_claude_adapter.py`
- `tests/plugins/test_cli_runtime.py`
- `tests/plugins/test_compactor.py`
- `tests/plugins/test_context_builder.py`
- `tests/plugins/test_dreamer.py`
- `tests/plugins/test_episodic_memory.py`
- `tests/plugins/test_hybrid_registry.py`
- `tests/plugins/test_infra_domain.py`
- `tests/plugins/test_jinja_builder.py`
- `tests/plugins/test_message_loop.py`
- `tests/plugins/test_reminder.py`
- `tests/plugins/test_safety_guard.py`
- `tests/plugins/test_server_runtime.py`
- `tests/plugins/test_spawner.py`
- `tests/plugins/test_working_memory.py`
- `tests/integration/test_multi_turn.py`
- `tests/integration/test_single_turn.py`
- `tests/integration/test_sub_agent.py`

- [ ] **Step 2: 테스트 파일 이름에서 v2_ 접두사 제거 (선택)**

```bash
git mv tests/core/test_v2_events.py tests/core/test_events.py
git mv tests/core/test_v2_container.py tests/core/test_container_di.py
git mv tests/core/test_v2_plugin.py tests/core/test_plugin.py
```

- [ ] **Step 3: 전체 테스트 실행**

Run: `python -m pytest tests/ -q --tb=line 2>&1 | tail -10`
Expected: 1509 passed, 4 failed (pre-existing)

- [ ] **Step 4: 커밋**

```bash
git add -A
git commit -m "refactor: update test imports and rename v2_ test files"
```

---

### Task 8: 잔여 v2_ 참조 확인 및 정리

- [ ] **Step 1: 잔여 참조 검색**

```bash
grep -rn "v2_events\|v2_container\|v2_plugin\|v2_builtin" src/ tests/ --include="*.py"
```

Expected: 0 results

- [ ] **Step 2: 빈 v2_builtin 디렉토리 제거 확인**

```bash
ls src/breadmind/plugins/v2_builtin/ 2>/dev/null && echo "STILL EXISTS" || echo "CLEAN"
```

Expected: CLEAN

- [ ] **Step 3: ruff lint**

Run: `ruff check src/breadmind/core/events.py src/breadmind/core/container.py src/breadmind/core/plugin.py src/breadmind/core/sandbox.py`

- [ ] **Step 4: 전체 테스트 최종 확인**

Run: `python -m pytest tests/ -q --tb=line 2>&1 | tail -10`
Expected: ~1509 passed, 4 failed (pre-existing)

- [ ] **Step 5: 최종 커밋 (필요 시)**

```bash
git add -A
git commit -m "chore: final cleanup — remove all v2_ references"
```
