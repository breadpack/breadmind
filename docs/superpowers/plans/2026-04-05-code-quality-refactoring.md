# BreadMind 코드 품질 리팩토링 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 코드 리뷰에서 도출된 75건 이상의 개선 항목을 8개 병렬 스트림으로 구현하여 코드 품질 점수를 49/100에서 75+/100으로 향상

**Architecture:** 8개 스트림을 2단계로 실행. Phase 1(Stream 1~5)은 독립적 기반 정리, Phase 2(Stream 6~8)은 아키텍처 리팩토링. 각 스트림은 worktree에서 격리 실행 후 병합.

**Tech Stack:** Python 3.12+, Pydantic v2, pydantic-settings, pytest-asyncio, YAML

---

## Stream 1: 데드코드 정리

### Task 1: 프로비저닝 전략 stub 제거

**Files:**
- Delete: `src/breadmind/provisioning/strategies/kubernetes.py`
- Delete: `src/breadmind/provisioning/strategies/proxmox.py`
- Delete: `src/breadmind/provisioning/strategies/ssh.py`
- Modify: `src/breadmind/provisioning/provisioner.py` (stub import 제거)
- Modify: `tests/test_provisioner.py` (stub 참조 제거)
- Keep: `src/breadmind/provisioning/strategies/base.py` (향후 구현용)

- [ ] **Step 1: provisioner.py에서 strategy import 확인 및 제거**

`src/breadmind/provisioning/provisioner.py`를 읽고, `kubernetes`, `proxmox`, `ssh` strategy를 import하는 부분을 제거한다. strategy를 직접 인스턴스화하는 코드가 있으면 해당 로직도 제거한다.

- [ ] **Step 2: 테스트 파일에서 stub 참조 제거**

`tests/test_provisioner.py`를 읽고, 삭제 대상 strategy를 참조하는 테스트를 제거한다. `base.py`의 `DeployStrategy` ABC를 테스트하는 코드는 유지한다.

- [ ] **Step 3: stub 파일 3개 삭제**

```bash
rm src/breadmind/provisioning/strategies/kubernetes.py
rm src/breadmind/provisioning/strategies/proxmox.py
rm src/breadmind/provisioning/strategies/ssh.py
```

- [ ] **Step 4: `__init__.py` 정리**

`src/breadmind/provisioning/strategies/__init__.py`가 있다면, 삭제된 모듈의 export를 제거한다.

- [ ] **Step 5: 테스트 실행**

```bash
python -m pytest tests/test_provisioner.py -v --tb=short
```
Expected: 남은 테스트 PASS

- [ ] **Step 6: Commit**

```bash
git add -A src/breadmind/provisioning/ tests/test_provisioner.py
git commit -m "refactor: remove unimplemented provisioning strategy stubs"
```

### Task 2: NotImplementedError 검색 프로바이더 정리

**Files:**
- Modify: `src/breadmind/tools/search_providers.py` (NotImplementedError 클래스 5개 제거)
- Modify: `tests/tools/test_search_providers.py` (관련 테스트 제거)

- [ ] **Step 1: search_providers.py 읽기 및 수정 범위 확인**

파일을 읽고, `ExaSearch`, `TavilySearch`, `FirecrawlSearch`, `SearXNGSearch` 클래스를 확인한다. `SearchProvider` 기본 클래스와 실제 구현이 있는 클래스(예: `DuckDuckGoSearch`)는 유지한다.

- [ ] **Step 2: NotImplementedError 클래스 제거**

`ExaSearch`, `TavilySearch`, `FirecrawlSearch`, `SearXNGSearch` 클래스를 삭제한다. `SearchProvider` ABC와 실제 동작하는 구현체는 유지한다. 파일 내 `__all__` 또는 export 목록도 업데이트한다.

- [ ] **Step 3: 테스트 파일 업데이트**

`tests/tools/test_search_providers.py`에서 삭제된 클래스 관련 테스트를 제거한다.

- [ ] **Step 4: 전체 코드베이스에서 삭제된 클래스 참조 검색**

```bash
grep -r "ExaSearch\|TavilySearch\|FirecrawlSearch\|SearXNGSearch" src/ tests/ --include="*.py" -l
```
발견된 파일에서 참조를 제거한다.

- [ ] **Step 5: 테스트 실행**

```bash
python -m pytest tests/tools/test_search_providers.py -v --tb=short
```

- [ ] **Step 6: Commit**

```bash
git add -A src/breadmind/tools/search_providers.py tests/tools/
git commit -m "refactor: remove unimplemented search provider stubs"
```

### Task 3: CodexAdapter 제거

**Files:**
- Delete: `src/breadmind/coding/adapters/codex.py`
- Modify: `src/breadmind/coding/adapters/__init__.py` (fallback dict에서 제거)
- Modify: `tests/test_coding_delegate.py` (Codex 참조 제거)

- [ ] **Step 1: __init__.py에서 CodexAdapter import 및 fallback 제거**

`src/breadmind/coding/adapters/__init__.py`를 읽고:
- `from breadmind.coding.adapters.codex import CodexAdapter` import 제거
- `_FALLBACK_ADAPTERS` dict에서 `"codex": CodexAdapter` 항목 제거
- `__all__`에서 `CodexAdapter` 제거

- [ ] **Step 2: 테스트에서 Codex 참조 제거**

`tests/test_coding_delegate.py`에서 `CodexAdapter` 관련 테스트를 제거한다.

- [ ] **Step 3: codex.py 파일 삭제**

```bash
rm src/breadmind/coding/adapters/codex.py
```

- [ ] **Step 4: 테스트 실행**

```bash
python -m pytest tests/test_coding_delegate.py -v --tb=short
```

- [ ] **Step 5: Commit**

```bash
git add -A src/breadmind/coding/adapters/ tests/test_coding_delegate.py
git commit -m "refactor: remove unused CodexAdapter"
```

---

## Stream 2: 하드코딩 해소

### Task 4: constants.py 생성 및 매직넘버 중앙화

**Files:**
- Create: `src/breadmind/constants.py`
- Create: `tests/test_constants.py`

- [ ] **Step 1: constants.py 작성**

```python
"""Central constants for BreadMind configuration defaults."""

# --- Network ---
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_CDP_URL = "http://localhost:9222"

# --- LLM Models ---
DEFAULT_PROVIDER = "gemini"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"
DEFAULT_CLAUDE_OPUS_MODEL = "claude-opus-4-6"

# --- LLM Token Limits ---
DEFAULT_MAX_TOKENS = 4096
THINKING_MAX_TOKENS = 16384
DEFAULT_THINK_BUDGET = 10000
TEXT_TRUNCATION_LIMIT = 2000

# --- Timeouts (seconds) ---
DEFAULT_TOOL_TIMEOUT = 30
DEFAULT_LLM_TIMEOUT = 120
DEFAULT_SSH_TIMEOUT = 300
DEFAULT_SESSION_TIMEOUT = 7200

# --- Web ---
DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8080
DEFAULT_WS_PORT = 8081

# --- Database ---
DEFAULT_DB_HOST = "localhost"
DEFAULT_DB_PORT = 5432
DEFAULT_DB_NAME = "breadmind"
DEFAULT_DB_USER = "breadmind"

# --- Limits ---
DEFAULT_MAX_TOOLS = 30
DEFAULT_MAX_CONTEXT_TOKENS = 4000
DEFAULT_MAX_TURNS = 10

# --- Network / Distributed ---
DEFAULT_HEARTBEAT_INTERVAL = 30
DEFAULT_OFFLINE_THRESHOLD = 90

# --- Memory ---
DEFAULT_GC_INTERVAL = 3600
DEFAULT_KG_MAX_AGE_DAYS = 90
DEFAULT_MAX_CACHED_NOTES = 500

# --- Embedding Models (provider defaults) ---
EMBEDDING_FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_OLLAMA_MODEL = "nomic-embed-text"
EMBEDDING_LOCAL_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_GEMINI_MODEL = "gemini-embedding-001"
EMBEDDING_OPENAI_MODEL = "text-embedding-3-small"

# --- Retry ---
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_BACKOFF = 1
DEFAULT_MAX_BACKOFF = 300
DEFAULT_GATEWAY_MAX_RETRIES = 10
```

- [ ] **Step 2: 간단한 import 테스트 작성**

```python
# tests/test_constants.py
from breadmind.constants import (
    DEFAULT_REDIS_URL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_WEB_PORT,
)

def test_constants_are_accessible():
    assert DEFAULT_REDIS_URL == "redis://localhost:6379/0"
    assert DEFAULT_MAX_TOKENS == 4096
    assert isinstance(DEFAULT_CLAUDE_MODEL, str)
    assert DEFAULT_WEB_PORT == 8080
```

- [ ] **Step 3: 테스트 실행**

```bash
python -m pytest tests/test_constants.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/breadmind/constants.py tests/test_constants.py
git commit -m "feat: add centralized constants module"
```

### Task 5: config.py 및 config_types.py에서 constants 사용

**Files:**
- Modify: `src/breadmind/config.py`
- Modify: `src/breadmind/config_types.py`

- [ ] **Step 1: config.py에서 하드코딩 값을 constants import로 대체**

`config.py`를 읽고, 다음을 변경:

```python
from breadmind.constants import (
    DEFAULT_PROVIDER, DEFAULT_MODEL, DEFAULT_WEB_HOST, DEFAULT_WEB_PORT,
    DEFAULT_DB_HOST, DEFAULT_DB_PORT, DEFAULT_DB_NAME, DEFAULT_DB_USER,
    DEFAULT_REDIS_URL, DEFAULT_SESSION_TIMEOUT, DEFAULT_WS_PORT,
    DEFAULT_HEARTBEAT_INTERVAL, DEFAULT_OFFLINE_THRESHOLD,
    DEFAULT_TOOL_TIMEOUT, DEFAULT_MAX_TURNS,
)
```

각 dataclass 필드의 기본값을 상수로 교체. 예:
- `port: int = 8080` → `port: int = DEFAULT_WEB_PORT`
- `host: str = "127.0.0.1"` → `host: str = DEFAULT_WEB_HOST`
- `default_model: str = "gemini-2.5-flash"` → `default_model: str = DEFAULT_MODEL`
- `redis_url: str = "redis://localhost:6379/0"` → `redis_url: str = DEFAULT_REDIS_URL`

- [ ] **Step 2: config_types.py에서 하드코딩 값을 constants import로 대체**

`config_types.py`를 읽고, 동일하게 상수 import로 대체:
- `interval_seconds: int = 3600` → `interval_seconds: int = DEFAULT_GC_INTERVAL`
- `kg_max_age_days: int = 90` → `kg_max_age_days: int = DEFAULT_KG_MAX_AGE_DAYS`
- `max_retries: int = 3` → `max_retries: int = DEFAULT_MAX_RETRIES`
- 등

- [ ] **Step 3: 기존 테스트 실행하여 회귀 확인**

```bash
python -m pytest tests/ -v --tb=short -x -q
```

- [ ] **Step 4: Commit**

```bash
git add src/breadmind/config.py src/breadmind/config_types.py
git commit -m "refactor: replace hardcoded values with constants in config modules"
```

### Task 6: Redis URL 중복 제거 및 LLM 모듈 하드코딩 해소

**Files:**
- Modify: `src/breadmind/tasks/celery_app.py`
- Modify: `src/breadmind/tasks/worker.py`
- Modify: `src/breadmind/llm/claude.py`
- Modify: `src/breadmind/llm/opus_plan.py`
- Modify: `src/breadmind/memory/embedding.py`

- [ ] **Step 1: celery_app.py와 worker.py에서 Redis URL 상수 사용**

```python
# celery_app.py - 변경
from breadmind.constants import DEFAULT_REDIS_URL
_redis_url = os.environ.get("BREADMIND_REDIS_URL", DEFAULT_REDIS_URL)
```

```python
# worker.py - 동일 변경
from breadmind.constants import DEFAULT_REDIS_URL
redis_url = os.environ.get("BREADMIND_REDIS_URL", DEFAULT_REDIS_URL)
```

- [ ] **Step 2: claude.py에서 모델명/토큰 상수 사용**

```python
from breadmind.constants import DEFAULT_CLAUDE_MODEL, DEFAULT_MAX_TOKENS, THINKING_MAX_TOKENS

# Line 27: default_model: str = DEFAULT_CLAUDE_MODEL
# Line 51: "max_tokens": THINKING_MAX_TOKENS if use_thinking else DEFAULT_MAX_TOKENS,
# Line 109: "max_tokens": DEFAULT_MAX_TOKENS,
```

- [ ] **Step 3: opus_plan.py에서 모델명 상수 사용**

```python
from breadmind.constants import DEFAULT_CLAUDE_OPUS_MODEL, DEFAULT_CLAUDE_MODEL

# Line 23: planning_model: str = DEFAULT_CLAUDE_OPUS_MODEL
# Line 24: implementation_model: str = DEFAULT_CLAUDE_MODEL
# Line 25: review_model: str = DEFAULT_CLAUDE_MODEL
```

- [ ] **Step 4: embedding.py에서 모델명 상수 사용**

```python
from breadmind.constants import (
    DEFAULT_OLLAMA_URL, EMBEDDING_FASTEMBED_MODEL, EMBEDDING_OLLAMA_MODEL,
    EMBEDDING_LOCAL_MODEL, EMBEDDING_GEMINI_MODEL, EMBEDDING_OPENAI_MODEL,
)
# 각 provider default를 상수로 대체
```

- [ ] **Step 5: 테스트 실행**

```bash
python -m pytest tests/ -v --tb=short -x -q
```

- [ ] **Step 6: Commit**

```bash
git add src/breadmind/tasks/ src/breadmind/llm/claude.py src/breadmind/llm/opus_plan.py src/breadmind/memory/embedding.py
git commit -m "refactor: centralize Redis URL and LLM model constants"
```

### Task 7: 모델 가격표 외부화

**Files:**
- Create: `config/model_pricing.yaml`
- Modify: `src/breadmind/plugins/builtin/agent_loop/cost_tracker.py`
- Modify: `src/breadmind/llm/base.py` (`_MODEL_PRICING` 중복 제거)

- [ ] **Step 1: config/model_pricing.yaml 생성**

```yaml
# Model pricing per million tokens (USD)
claude-sonnet-4-6:
  input: 3.0
  output: 15.0
  cache_creation: 3.75
  cache_read: 0.30
claude-haiku-4-5:
  input: 0.80
  output: 4.0
  cache_creation: 1.0
  cache_read: 0.08
claude-opus-4-6:
  input: 15.0
  output: 75.0
  cache_creation: 18.75
  cache_read: 1.50
gemini-2.5-flash:
  input: 0.15
  output: 0.60
gemini-2.5-pro:
  input: 1.25
  output: 10.0
grok-3:
  input: 3.0
  output: 15.0
grok-3-mini:
  input: 0.30
  output: 0.50
```

- [ ] **Step 2: cost_tracker.py에서 YAML 로딩으로 변경**

`cost_tracker.py`를 읽고, `MODEL_PRICING` dict를 YAML 파일에서 로드하도록 변경한다. 파일을 찾을 수 없으면 기존 하드코딩 값을 fallback으로 사용한다.

```python
import yaml
from pathlib import Path

_PRICING_FILE = Path(__file__).resolve().parents[5] / "config" / "model_pricing.yaml"

_FALLBACK_PRICING = {
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_creation": 3.75, "cache_read": 0.30},
    # ... (기존 값 유지)
}

def _load_pricing() -> dict:
    try:
        if _PRICING_FILE.exists():
            with open(_PRICING_FILE, encoding="utf-8") as f:
                return yaml.safe_load(f)
    except Exception:
        pass
    return _FALLBACK_PRICING

MODEL_PRICING: dict = _load_pricing()
```

- [ ] **Step 3: llm/base.py에서 `_MODEL_PRICING` 제거, cost_tracker에서 import**

`llm/base.py`의 `_MODEL_PRICING` dict(lines 11-25)를 삭제하고, 이를 참조하는 코드가 있으면 `cost_tracker.py`의 `MODEL_PRICING`을 import하도록 변경한다.

- [ ] **Step 4: 테스트 실행**

```bash
python -m pytest tests/ -v --tb=short -x -q
```

- [ ] **Step 5: Commit**

```bash
git add config/model_pricing.yaml src/breadmind/plugins/builtin/agent_loop/cost_tracker.py src/breadmind/llm/base.py
git commit -m "refactor: externalize model pricing to YAML config"
```

---

## Stream 3: 중복 데이터클래스 통합

### Task 8: protocols/provider.py 중복 정의 정리

**Files:**
- Modify: `src/breadmind/core/protocols/provider.py` (중복 dataclass 제거, llm.base에서 re-export)
- Modify: `src/breadmind/core/protocols/__init__.py`
- Modify: 12개 import 파일 (필요 시)

- [ ] **Step 1: 두 파일의 중복 클래스 비교**

`core/protocols/provider.py`와 `llm/base.py`를 읽고, 다음을 확인:
- `ToolCallRequest` vs `ToolCall`: 필드명 차이 파악
- `TokenUsage`: 필드명 차이 파악
- `LLMResponse`: 필드명 차이 파악
- `Message` vs `LLMMessage`: 필드명 차이 파악

**중요**: 두 파일의 클래스가 필드명이 다를 수 있으므로, 먼저 정확한 필드를 비교한 후 통합 전략을 결정한다.

- [ ] **Step 2: llm/base.py를 정본으로, protocols/provider.py에서 re-export**

`protocols/provider.py`에서 중복된 dataclass 정의를 삭제하고, `llm.base`에서 import하여 re-export한다. 이렇게 하면 기존 import 경로가 깨지지 않는다.

```python
# core/protocols/provider.py - 변경 후
from breadmind.llm.base import ToolCall, TokenUsage, LLMResponse, LLMMessage

# 기존 이름이 다른 경우 alias:
ToolCallRequest = ToolCall  # 하위 호환
Message = LLMMessage  # 하위 호환

# ProviderProtocol은 그대로 유지 (프로토콜 정의는 여기 고유)
```

- [ ] **Step 3: protocols/__init__.py에서 export 확인 및 업데이트**

`core/protocols/__init__.py`가 provider.py의 클래스를 re-export하고 있다면, 변경 사항 반영.

- [ ] **Step 4: 전체 import 경로 테스트**

```bash
python -c "from breadmind.core.protocols.provider import ToolCallRequest, TokenUsage, LLMResponse, Message; print('OK')"
python -c "from breadmind.llm.base import ToolCall, TokenUsage, LLMResponse; print('OK')"
```

- [ ] **Step 5: 전체 테스트 실행**

```bash
python -m pytest tests/ -v --tb=short -x -q
```

- [ ] **Step 6: Commit**

```bash
git add src/breadmind/core/protocols/ src/breadmind/llm/base.py
git commit -m "refactor: consolidate duplicate data classes to llm.base as single source"
```

---

## Stream 4: 메신저 게이트웨이 리팩토링

### Task 9: MessengerGateway 기본 클래스 강화

**Files:**
- Modify: `src/breadmind/messenger/router.py` (기존 MessengerGateway ABC 강화)

- [ ] **Step 1: router.py의 현재 MessengerGateway 확인**

파일을 읽고 현재 ABC의 메서드 시그니처, 데이터클래스(`IncomingMessage`, `OutgoingMessage`, `ApprovalRequest`), 공통 패턴을 파악한다.

- [ ] **Step 2: 공통 로직을 기본 클래스에 추가**

```python
class MessengerGateway(ABC):
    """Enhanced base class with common gateway logic."""

    def __init__(self, platform: str, on_message: Callable | None = None):
        self.platform = platform
        self._on_message = on_message
        self._connected = False
        self._enabled = True

    def _create_incoming_message(
        self, text: str, user: str, channel: str, **kwargs
    ) -> IncomingMessage:
        """Factory method for creating IncomingMessage with standard fields."""
        return IncomingMessage(
            id=uuid.uuid4().hex[:8],
            text=text,
            user=user,
            channel=channel,
            platform=self.platform,
            **kwargs,
        )

    def _generate_action_id(self) -> str:
        """Generate a short unique action ID for approvals."""
        return uuid.uuid4().hex[:8]

    async def ask_approval(
        self, channel_id: str, action_name: str, params: dict
    ) -> str:
        """Default approval implementation. Override for platform-specific formatting."""
        action_id = self._generate_action_id()
        text = self._format_approval_message(action_name, params, action_id)
        await self.send(channel_id, text)
        return action_id

    def _format_approval_message(
        self, action_name: str, params: dict, action_id: str
    ) -> str:
        """Override in subclasses for platform-specific formatting."""
        param_str = ", ".join(f"{k}={v}" for k, v in params.items())
        return f"[Approval Required] {action_name}({param_str})\nApprove: /approve {action_id}\nDeny: /deny {action_id}"

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def send(self, channel_id: str, text: str) -> None: ...
```

`ask_approval()`은 더 이상 abstract가 아니다. 기본 구현을 제공하고, 서브클래스는 `_format_approval_message()`만 오버라이드한다.

- [ ] **Step 3: 테스트 실행**

```bash
python -m pytest tests/messenger/ -v --tb=short
```

- [ ] **Step 4: Commit**

```bash
git add src/breadmind/messenger/router.py
git commit -m "refactor: enhance MessengerGateway base with common logic"
```

### Task 10: 메신저 게이트웨이 서브클래스 리팩토링

**Files:**
- Modify: `src/breadmind/messenger/slack.py`
- Modify: `src/breadmind/messenger/discord_gw.py`
- Modify: `src/breadmind/messenger/telegram_gw.py`
- Modify: `src/breadmind/messenger/whatsapp_gw.py`
- Modify: `src/breadmind/messenger/signal_gw.py`
- Modify: `src/breadmind/messenger/gmail_gw.py`
- Modify: `src/breadmind/messenger/line_gw.py`
- Modify: `src/breadmind/messenger/matrix_gw.py`
- Modify: `src/breadmind/messenger/teams_gw.py`

- [ ] **Step 1: slack.py 리팩토링 (패턴 확립)**

`slack.py`를 읽고 리팩토링한다:
- `__init__()`: `super().__init__(platform="slack", on_message=on_message)` 호출
- `ask_approval()`: 기본 클래스 구현 사용, `_format_approval_message()` 오버라이드 (Slack Block Kit 포맷 필요 시)
- `uuid.uuid4()[:8]` 직접 호출 → `self._generate_action_id()` 사용
- `IncomingMessage` 직접 생성 → `self._create_incoming_message()` 사용

- [ ] **Step 2: discord_gw.py 리팩토링**

동일한 패턴 적용. Discord-specific: embed 포맷팅이 필요하면 `_format_approval_message()` 오버라이드.

- [ ] **Step 3: telegram_gw.py 리팩토링**

동일 패턴 적용. Telegram-specific: inline keyboard 포맷팅이 필요하면 오버라이드.

- [ ] **Step 4: 나머지 6개 게이트웨이 리팩토링**

`whatsapp_gw.py`, `signal_gw.py`, `gmail_gw.py`, `line_gw.py`, `matrix_gw.py`, `teams_gw.py` 각각에 동일 패턴 적용.

- [ ] **Step 5: 전체 메신저 테스트 실행**

```bash
python -m pytest tests/messenger/ -v --tb=short
```

- [ ] **Step 6: Commit**

```bash
git add src/breadmind/messenger/
git commit -m "refactor: deduplicate messenger gateways using enhanced base class"
```

---

## Stream 5: 공통 유틸리티 모듈

### Task 11: utils 패키지 생성

**Files:**
- Create: `src/breadmind/utils/__init__.py`
- Create: `src/breadmind/utils/helpers.py`
- Create: `src/breadmind/utils/serialization.py`
- Create: `tests/test_utils.py`

- [ ] **Step 1: utils 디렉토리 및 __init__.py 생성**

```bash
mkdir -p src/breadmind/utils
```

```python
# src/breadmind/utils/__init__.py
"""Common utilities for BreadMind."""
```

- [ ] **Step 2: helpers.py 작성**

```python
"""Common helper functions used across BreadMind modules."""

from __future__ import annotations

import asyncio
import uuid
from importlib import import_module
from typing import Any


def generate_short_id(length: int = 8) -> str:
    """Generate a short unique ID from UUID4 hex."""
    return uuid.uuid4().hex[:length]


async def cancel_task_safely(task: asyncio.Task | None) -> None:
    """Cancel an asyncio task and suppress CancelledError."""
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def safe_import(module_path: str, package_display_name: str | None = None) -> Any:
    """Import a module, returning None if not installed.

    Args:
        module_path: Dotted import path (e.g., "slack_bolt.async_app").
        package_display_name: Name to show in warning (defaults to module_path).

    Returns:
        The imported module, or None if ImportError.
    """
    try:
        return import_module(module_path)
    except ImportError:
        return None
```

- [ ] **Step 3: serialization.py 작성**

```python
"""Serialization mixin for dataclasses."""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar

T = TypeVar("T")


def _default_serializer(obj: Any) -> Any:
    """JSON serializer for types not handled by default."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class SerializableMixin:
    """Mixin that adds to_dict/from_dict/to_json/from_json to dataclasses."""

    def to_dict(self) -> dict[str, Any]:
        """Convert dataclass to dict with proper type handling."""
        return json.loads(json.dumps(dataclasses.asdict(self), default=_default_serializer))

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        """Create instance from dict, ignoring unknown fields."""
        field_names = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in field_names}
        return cls(**filtered)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls: type[T], json_str: str) -> T:
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))
```

- [ ] **Step 4: 테스트 작성**

```python
# tests/test_utils.py
import asyncio
import dataclasses
from datetime import datetime
from enum import Enum

from breadmind.utils.helpers import generate_short_id, cancel_task_safely, safe_import
from breadmind.utils.serialization import SerializableMixin


def test_generate_short_id_default_length():
    sid = generate_short_id()
    assert len(sid) == 8
    assert sid.isalnum()


def test_generate_short_id_custom_length():
    sid = generate_short_id(12)
    assert len(sid) == 12


async def test_cancel_task_safely_with_none():
    await cancel_task_safely(None)  # should not raise


async def test_cancel_task_safely_with_running_task():
    async def long_running():
        await asyncio.sleep(100)

    task = asyncio.create_task(long_running())
    await cancel_task_safely(task)
    assert task.cancelled()


def test_safe_import_existing_module():
    mod = safe_import("json")
    assert mod is not None


def test_safe_import_missing_module():
    mod = safe_import("nonexistent_module_xyz")
    assert mod is None


class Status(Enum):
    ACTIVE = "active"
    DONE = "done"


@dataclasses.dataclass
class SampleModel(SerializableMixin):
    name: str
    count: int
    status: Status = Status.ACTIVE
    created: datetime | None = None


def test_serializable_to_dict():
    obj = SampleModel(name="test", count=5, status=Status.DONE)
    d = obj.to_dict()
    assert d["name"] == "test"
    assert d["count"] == 5
    assert d["status"] == "done"


def test_serializable_from_dict():
    obj = SampleModel.from_dict({"name": "x", "count": 1, "extra_field": "ignored"})
    assert obj.name == "x"
    assert obj.count == 1


def test_serializable_roundtrip_json():
    obj = SampleModel(name="test", count=3)
    json_str = obj.to_json()
    restored = SampleModel.from_json(json_str)
    assert restored.name == obj.name
    assert restored.count == obj.count
```

- [ ] **Step 5: 테스트 실행**

```bash
python -m pytest tests/test_utils.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/breadmind/utils/ tests/test_utils.py
git commit -m "feat: add common utilities module (helpers, serialization)"
```

### Task 12: 기존 코드에서 유틸리티 사용으로 마이그레이션

**Files:**
- Modify: 메신저 게이트웨이 파일들 (uuid 패턴)
- Modify: `src/breadmind/core/defer_manager.py` (to_dict/from_dict)
- Modify: `src/breadmind/coding/job_tracker.py` (to_dict)
- Modify: `src/breadmind/messenger/signal_gw.py` (cancel_task_safely)
- Modify: `src/breadmind/messenger/gmail_gw.py` (cancel_task_safely)

- [ ] **Step 1: uuid 패턴 마이그레이션**

메신저 게이트웨이가 이미 Task 10에서 `_generate_action_id()` 사용으로 전환되었으므로, 그 외 파일에서 `uuid.uuid4().hex[:8]` 패턴을 검색하여 `generate_short_id()` 사용으로 변경한다.

```bash
grep -rn "uuid4().hex\[:" src/breadmind/ --include="*.py" -l
```

각 파일에서:
```python
from breadmind.utils.helpers import generate_short_id
# uuid.uuid4().hex[:8] → generate_short_id()
```

- [ ] **Step 2: cancel_task_safely 마이그레이션**

`signal_gw.py`, `gmail_gw.py` 등에서 비동기 취소 패턴을 `cancel_task_safely()` 호출로 변경.

- [ ] **Step 3: SerializableMixin 점진적 적용**

`core/defer_manager.py`, `coding/job_tracker.py` 등에서 수동 `to_dict()`/`from_dict()`가 있는 dataclass에 `SerializableMixin`을 추가한다. 단, 기존 동작이 변경되지 않도록 기존 메서드를 먼저 비교한 후 적용한다.

**주의**: 기존 `to_dict()` 메서드가 커스텀 로직(예: 특정 필드 변환)을 가지고 있으면 Mixin 대신 기존 코드를 유지한다.

- [ ] **Step 4: 테스트 실행**

```bash
python -m pytest tests/ -v --tb=short -x -q
```

- [ ] **Step 5: Commit**

```bash
git add -A src/breadmind/
git commit -m "refactor: migrate to common utility functions"
```

---

## Stream 6: CoreAgent 책임 분리

### Task 13: ConversationManager 추출

**Files:**
- Create: `src/breadmind/core/conversation_manager.py`
- Create: `tests/core/test_conversation_manager.py`
- Modify: `src/breadmind/core/agent.py`

- [ ] **Step 1: agent.py에서 대화 관리 로직 식별**

`agent.py`를 읽고, `handle_message()` 메서드(lines 294-614)에서 다음 책임을 식별:
1. 메시지 히스토리 구성 (working_memory 조회)
2. 컨텍스트 enrichment (context_builder 호출)
3. 메시지 summarization (summarizer 호출)
4. Token counting

- [ ] **Step 2: ConversationManager 클래스 작성**

```python
# src/breadmind/core/conversation_manager.py
"""Manages conversation history, context, and token budgets."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ConversationManager:
    """Handles message history assembly, context enrichment, and summarization."""

    def __init__(
        self,
        working_memory: Any | None = None,
        context_builder: Any | None = None,
        summarizer: Any | None = None,
        prompt_builder: Any | None = None,
        prompt_context: Any | None = None,
    ):
        self._working_memory = working_memory
        self._context_builder = context_builder
        self._summarizer = summarizer
        self._prompt_builder = prompt_builder
        self._prompt_context = prompt_context

    async def build_messages(
        self, user_message: str, system_prompt: str, user: str, channel: str
    ) -> list[dict]:
        """Assemble message list from history, context, and current input."""
        messages = []
        # 1. Working memory history
        if self._working_memory is not None:
            messages = self._working_memory.get_messages()
        # 2. Add current user message
        messages.append({"role": "user", "content": user_message})
        return messages

    async def enrich_context(
        self, messages: list[dict], user_message: str
    ) -> list[dict]:
        """Add context from context_builder if available."""
        if self._context_builder is not None:
            context = await self._context_builder.build(user_message)
            if context:
                messages = [{"role": "system", "content": context}] + messages
        return messages

    async def maybe_summarize(
        self, messages: list[dict], max_tokens: int
    ) -> list[dict]:
        """Summarize older messages if token budget is exceeded."""
        if self._summarizer is None:
            return messages
        # Delegate to summarizer's logic
        return await self._summarizer.compact_if_needed(messages, max_tokens)
```

**주의**: 실제 구현은 `agent.py`의 `handle_message()` 내부 로직을 정확히 추출한 것이어야 한다. 위 코드는 구조 예시이며, 실제 추출 시 `handle_message()`의 해당 부분을 그대로 옮긴다.

- [ ] **Step 3: 테스트 작성**

```python
# tests/core/test_conversation_manager.py
from breadmind.core.conversation_manager import ConversationManager


async def test_build_messages_without_memory():
    cm = ConversationManager()
    msgs = await cm.build_messages("hello", "system", "user1", "ch1")
    assert len(msgs) == 1
    assert msgs[0]["content"] == "hello"


async def test_enrich_context_without_builder():
    cm = ConversationManager()
    msgs = [{"role": "user", "content": "hello"}]
    result = await cm.enrich_context(msgs, "hello")
    assert result == msgs
```

- [ ] **Step 4: 테스트 실행**

```bash
python -m pytest tests/core/test_conversation_manager.py -v
```

- [ ] **Step 5: agent.py에서 ConversationManager 사용**

`agent.py`의 `__init__()`에서 `ConversationManager`를 생성하고, `handle_message()`의 메시지 빌드/컨텍스트/요약 로직을 `ConversationManager` 메서드 호출로 대체한다.

- [ ] **Step 6: agent.py 테스트 실행**

```bash
python -m pytest tests/core/test_agent*.py tests/test_agent*.py -v --tb=short
```

- [ ] **Step 7: Commit**

```bash
git add src/breadmind/core/conversation_manager.py tests/core/test_conversation_manager.py src/breadmind/core/agent.py
git commit -m "refactor: extract ConversationManager from CoreAgent"
```

### Task 14: ToolCoordinator 추출

**Files:**
- Create: `src/breadmind/core/tool_coordinator.py`
- Create: `tests/core/test_tool_coordinator.py`
- Modify: `src/breadmind/core/agent.py`

- [ ] **Step 1: agent.py에서 도구 관련 로직 식별**

`handle_message()` 내에서:
1. `_filter_relevant_tools()` (line 643) — 도구 필터링
2. Tool call 루프 (main for loop 내부) — 도구 실행 + 결과 처리
3. Loop detection — 반복 도구 호출 감지
4. 도구 승인 관련: `approve_tool()`, `deny_tool()`, `resume_after_approval()`

- [ ] **Step 2: ToolCoordinator 클래스 작성**

```python
# src/breadmind/core/tool_coordinator.py
"""Coordinates tool filtering, execution, and loop detection."""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ToolCoordinator:
    """Handles tool selection, execution loops, and approval management."""

    def __init__(
        self,
        tool_registry: Any,
        tool_executor: Any,
        safety_guard: Any,
        tool_timeout: int = 30,
        audit_logger: Any | None = None,
    ):
        self._registry = tool_registry
        self._executor = tool_executor
        self._guard = safety_guard
        self._tool_timeout = tool_timeout
        self._audit_logger = audit_logger
        self._pending_approvals: dict[str, dict] = {}

    def filter_relevant_tools(
        self, tools: list, message: str, max_tools: int = 30, intent: Any = None
    ) -> list:
        """Filter tools relevant to the current message context."""
        # Extract logic from agent.py _filter_relevant_tools()
        ...

    async def execute_tool_calls(
        self, tool_calls: list, user: str, channel: str
    ) -> list[dict]:
        """Execute a batch of tool calls with safety checks."""
        # Extract tool execution loop from handle_message()
        ...

    def detect_loop(self, recent_calls: list[str], threshold: int = 3) -> bool:
        """Detect if the agent is stuck in a tool call loop."""
        ...

    def get_pending_approvals(self) -> list[dict]:
        return list(self._pending_approvals.values())

    async def approve_tool(self, approval_id: str) -> Any:
        """Approve and execute a pending tool call."""
        ...

    def deny_tool(self, approval_id: str) -> None:
        """Deny a pending tool call."""
        ...
```

**주의**: 실제 구현은 `agent.py`의 해당 로직을 정확히 추출해야 한다.

- [ ] **Step 3: 테스트 작성**

ToolCoordinator의 핵심 메서드에 대한 단위 테스트를 작성한다. mock된 tool_registry, tool_executor, safety_guard를 사용한다.

- [ ] **Step 4: 테스트 실행**

```bash
python -m pytest tests/core/test_tool_coordinator.py -v
```

- [ ] **Step 5: agent.py에서 ToolCoordinator 사용**

`agent.py`의 `__init__()`에서 `ToolCoordinator`를 생성하고, 도구 관련 로직을 위임한다. `approve_tool()`, `deny_tool()`, `resume_after_approval()`, `_filter_relevant_tools()`, tool call 루프를 `ToolCoordinator` 호출로 대체한다.

- [ ] **Step 6: 전체 에이전트 테스트 실행**

```bash
python -m pytest tests/core/test_agent*.py tests/test_agent*.py -v --tb=short
```

- [ ] **Step 7: Commit**

```bash
git add src/breadmind/core/tool_coordinator.py tests/core/test_tool_coordinator.py src/breadmind/core/agent.py
git commit -m "refactor: extract ToolCoordinator from CoreAgent"
```

---

## Stream 7: bootstrap_all() 리팩토링

### Task 15: AppComponents 계층화

**Files:**
- Create: `src/breadmind/core/bootstrap/` (패키지)
- Create: `src/breadmind/core/bootstrap/__init__.py`
- Create: `src/breadmind/core/bootstrap/components.py`
- Modify: `src/breadmind/core/bootstrap.py` (re-export 유지)

- [ ] **Step 1: bootstrap 패키지 생성**

```bash
mkdir -p src/breadmind/core/bootstrap
```

- [ ] **Step 2: components.py 작성 — 계층화된 AppComponents**

```python
# src/breadmind/core/bootstrap/components.py
"""Hierarchical application component containers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DatabaseComponents:
    db: Any = None
    credential_vault: Any = None


@dataclass
class LLMComponents:
    provider: Any = None
    profiler: Any = None


@dataclass
class MemoryComponents:
    working_memory: Any = None
    episodic_memory: Any = None
    semantic_memory: Any = None
    smart_retriever: Any = None
    context_builder: Any = None


@dataclass
class ToolComponents:
    registry: Any = None
    guard: Any = None
    meta_tools: Any = None
    tool_gap_detector: Any = None


@dataclass
class PluginComponents:
    plugin_mgr: Any = None
    skill_store: Any = None
    mcp_manager: Any = None
    mcp_store: Any = None


@dataclass
class MessengerComponents:
    # messenger gateways stored by platform name
    pass


@dataclass
class MonitoringComponents:
    monitoring_engine: Any = None
    behavior_tracker: Any = None
    performance_tracker: Any = None
    metrics_collector: Any = None
    audit_logger: Any = None


@dataclass
class NetworkComponents:
    swarm_manager: Any = None
    event_bus: Any = None


@dataclass
class PersonalComponents:
    personal_scheduler: Any = None
    oauth_manager: Any = None
    adapter_registry: Any = None
    search_engine: Any = None


@dataclass
class AppComponents:
    """Top-level container grouping sub-component categories."""
    config: Any = None
    safety_cfg: Any = None
    container: Any = None

    database: DatabaseComponents = field(default_factory=DatabaseComponents)
    llm: LLMComponents = field(default_factory=LLMComponents)
    memory: MemoryComponents = field(default_factory=MemoryComponents)
    tools: ToolComponents = field(default_factory=ToolComponents)
    plugins: PluginComponents = field(default_factory=PluginComponents)
    messenger: MessengerComponents = field(default_factory=MessengerComponents)
    monitoring: MonitoringComponents = field(default_factory=MonitoringComponents)
    network: NetworkComponents = field(default_factory=NetworkComponents)
    personal: PersonalComponents = field(default_factory=PersonalComponents)

    agent: Any = None
    bg_job_manager: Any = None

    # --- Backward compatibility properties ---
    @property
    def db(self):
        return self.database.db

    @db.setter
    def db(self, value):
        self.database.db = value

    @property
    def provider(self):
        return self.llm.provider

    @provider.setter
    def provider(self, value):
        self.llm.provider = value

    @property
    def registry(self):
        return self.tools.registry

    @registry.setter
    def registry(self, value):
        self.tools.registry = value

    @property
    def guard(self):
        return self.tools.guard

    @guard.setter
    def guard(self, value):
        self.tools.guard = value

    @property
    def working_memory(self):
        return self.memory.working_memory

    @working_memory.setter
    def working_memory(self, value):
        self.memory.working_memory = value

    @property
    def monitoring_engine(self):
        return self.monitoring.monitoring_engine

    @monitoring_engine.setter
    def monitoring_engine(self, value):
        self.monitoring.monitoring_engine = value

    @property
    def plugin_mgr(self):
        return self.plugins.plugin_mgr

    @plugin_mgr.setter
    def plugin_mgr(self, value):
        self.plugins.plugin_mgr = value

    # Add remaining backward-compat properties for all 37 original fields
    # that are now nested in sub-components...
```

**주의**: 하위 호환 property를 기존 `AppComponents`의 모든 필드에 대해 추가해야 한다. 실제 구현 시 기존 `bootstrap.py`의 `AppComponents` 필드 목록을 참고하여 빠짐없이 추가한다.

- [ ] **Step 3: __init__.py에서 export**

```python
# src/breadmind/core/bootstrap/__init__.py
from breadmind.core.bootstrap.components import (
    AppComponents,
    DatabaseComponents,
    LLMComponents,
    MemoryComponents,
    ToolComponents,
    PluginComponents,
    MessengerComponents,
    MonitoringComponents,
    NetworkComponents,
    PersonalComponents,
)
```

- [ ] **Step 4: 기존 bootstrap.py에서 새 AppComponents import**

기존 `core/bootstrap.py`의 `AppComponents` 정의를 삭제하고:
```python
from breadmind.core.bootstrap.components import AppComponents
```
로 대체한다. 나머지 코드는 하위 호환 property 덕분에 변경 불필요.

- [ ] **Step 5: 테스트 실행**

```bash
python -m pytest tests/ -v --tb=short -x -q
```

- [ ] **Step 6: Commit**

```bash
git add src/breadmind/core/bootstrap/ src/breadmind/core/bootstrap.py
git commit -m "refactor: hierarchize AppComponents into sub-component groups"
```

### Task 16: bootstrap_all()을 Phase별 함수로 분리

**Files:**
- Create: `src/breadmind/core/bootstrap/phases.py`
- Modify: `src/breadmind/core/bootstrap.py` (bootstrap_all 축소)

- [ ] **Step 1: 기존 bootstrap_all()의 각 Phase를 독립 함수로 추출**

`bootstrap.py`의 `bootstrap_all()` (lines 626-788)을 읽고, 각 Phase의 로직을 `phases.py`의 독립 함수로 추출한다:

```python
# src/breadmind/core/bootstrap/phases.py
"""Individual bootstrap phases, each initializing one subsystem."""

from __future__ import annotations

import logging
from typing import Any

from breadmind.core.bootstrap.components import AppComponents

logger = logging.getLogger(__name__)


async def init_phase_database(components: AppComponents, config: Any, config_dir: str) -> None:
    """Phase 1: Initialize database connection."""
    # Extract Phase 1 logic from bootstrap_all()
    ...


async def init_phase_credentials(components: AppComponents) -> None:
    """Phase 1.5: Initialize credential vault."""
    # Extract Phase 1.5 logic
    ...


async def init_phase_core_services(components: AppComponents, config: Any, safety_cfg: Any) -> None:
    """Phase 2: Initialize core services (ServiceContainer)."""
    # Extract Phase 2 logic
    ...


async def init_phase_plugins(components: AppComponents, config: Any) -> None:
    """Phase 4: Load plugins."""
    ...


async def init_phase_agent(
    components: AppComponents, config: Any, provider: Any, safety_cfg: Any
) -> None:
    """Phase 5: Initialize agent."""
    ...


async def init_phase_messengers(components: AppComponents, message_router: Any) -> None:
    """Phase 6: Connect messengers."""
    ...


async def init_phase_background(components: AppComponents, event_callback: Any) -> None:
    """Phase 7: Start background jobs."""
    ...


async def init_phase_personal(components: AppComponents) -> None:
    """Phase 8: Personal scheduler."""
    ...
```

- [ ] **Step 2: bootstrap_all()을 Phase 함수 호출로 축소**

기존 `bootstrap_all()`의 본문을 Phase 함수 호출 시퀀스로 대체:

```python
async def bootstrap_all(config, config_dir, safety_cfg, provider, message_router=None, event_callback=None):
    components = AppComponents(config=config, safety_cfg=safety_cfg)

    await init_phase_database(components, config, config_dir)
    await init_phase_credentials(components)
    await init_phase_core_services(components, config, safety_cfg)
    await init_phase_plugins(components, config)
    await init_phase_agent(components, config, provider, safety_cfg)
    await init_phase_messengers(components, message_router)
    await init_phase_background(components, event_callback)
    await init_phase_personal(components)

    return components
```

각 Phase 함수 내부에 기존의 try/except 패턴을 유지한다.

- [ ] **Step 3: 테스트 실행**

```bash
python -m pytest tests/ -v --tb=short -x -q
```

- [ ] **Step 4: Commit**

```bash
git add src/breadmind/core/bootstrap/ src/breadmind/core/bootstrap.py
git commit -m "refactor: split bootstrap_all into independent phase functions"
```

---

## Stream 8: 설정 시스템 Pydantic 단일화

### Task 17: config.py를 Pydantic BaseModel로 전환

**Files:**
- Modify: `src/breadmind/config.py` (dataclass → Pydantic BaseModel)
- Modify: `src/breadmind/config_types.py` (dataclass → Pydantic BaseModel)
- Modify: `src/breadmind/core/config_schema.py` (검증 통합)
- Create: `tests/test_config_pydantic.py`

- [ ] **Step 1: config.py 전체 읽기 및 변환 계획 수립**

`config.py`를 전체 읽고, 모든 `@dataclass` 클래스를 `BaseModel`로 변환할 목록을 작성한다. 각 클래스의 필드 타입, 기본값, validator가 필요한 필드를 확인한다.

- [ ] **Step 2: config.py의 설정 클래스를 Pydantic BaseModel로 변환**

기존:
```python
@dataclass
class WebConfig:
    host: str = "127.0.0.1"
    port: int = 8080
```

변환 후:
```python
from pydantic import BaseModel
from breadmind.constants import DEFAULT_WEB_HOST, DEFAULT_WEB_PORT

class WebConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    host: str = DEFAULT_WEB_HOST
    port: int = DEFAULT_WEB_PORT
```

모든 설정 클래스에 동일 적용: `WebConfig`, `LoggingConfig`, `LLMConfig`, `DatabaseConfig`, `SecurityConfig`, `TaskConfig`, `NetworkConfig`, 루트 `AppConfig`.

- [ ] **Step 3: config_types.py도 Pydantic으로 변환**

`MemoryGCConfig`, `TimeoutsConfig`, `RetryConfig`, `LimitsConfig`, `EmbeddingConfig` 등.

- [ ] **Step 4: config_schema.py 통합**

`config_schema.py`의 Pydantic 스키마들이 이제 `config.py`와 중복이므로:
- `config_schema.py`의 중복 스키마를 삭제
- `validate_config()` 함수는 `config.py`의 Pydantic 모델을 직접 사용하도록 변경
- opt-in 검증 제거 (Pydantic은 항상 검증)

- [ ] **Step 5: config_profiles.py가 Pydantic 모델과 호환되도록 업데이트**

`load_with_profile()`이 반환하는 dict를 `AppConfig.model_validate()`로 파싱하도록 변경.

- [ ] **Step 6: 마이그레이션 테스트 작성**

```python
# tests/test_config_pydantic.py
from breadmind.config import WebConfig, LLMConfig, DatabaseConfig, AppConfig
from breadmind.constants import DEFAULT_WEB_PORT, DEFAULT_MODEL


def test_web_config_defaults():
    cfg = WebConfig()
    assert cfg.port == DEFAULT_WEB_PORT


def test_llm_config_defaults():
    cfg = LLMConfig()
    assert cfg.default_model == DEFAULT_MODEL


def test_config_validation_rejects_invalid():
    from pydantic import ValidationError
    import pytest
    with pytest.raises(ValidationError):
        WebConfig(port="not_a_number")


def test_config_extra_fields_ignored():
    cfg = WebConfig(host="0.0.0.0", unknown_field="ignored")
    assert cfg.host == "0.0.0.0"


def test_app_config_from_dict():
    data = {"web": {"port": 9090}, "llm": {"default_model": "grok-3"}}
    cfg = AppConfig.model_validate(data)
    assert cfg.web.port == 9090
    assert cfg.llm.default_model == "grok-3"
```

- [ ] **Step 7: 테스트 실행**

```bash
python -m pytest tests/test_config_pydantic.py tests/test_config*.py -v --tb=short
```

- [ ] **Step 8: 전체 테스트 실행**

```bash
python -m pytest tests/ -v --tb=short -x -q
```

- [ ] **Step 9: Commit**

```bash
git add src/breadmind/config.py src/breadmind/config_types.py src/breadmind/core/config_schema.py src/breadmind/core/config_profiles.py tests/test_config_pydantic.py
git commit -m "refactor: unify config system to Pydantic v2 BaseModel"
```

---

## 최종 통합

### Task 18: 전체 회귀 테스트 및 린트

**Files:** 전체 코드베이스

- [ ] **Step 1: 전체 테스트 스위트 실행**

```bash
python -m pytest tests/ -v --tb=short --cov=breadmind --cov-fail-under=55
```
Expected: 모든 테스트 PASS, 커버리지 55% 이상

- [ ] **Step 2: 린트 실행**

```bash
ruff check src/ tests/
```
Expected: 오류 없음 (새로운 lint 오류가 있으면 수정)

- [ ] **Step 3: import 순환 검사**

```bash
python -c "import breadmind; print('Import OK')"
```

- [ ] **Step 4: 최종 Commit**

```bash
git add -A
git commit -m "chore: final cleanup after code quality refactoring"
```
