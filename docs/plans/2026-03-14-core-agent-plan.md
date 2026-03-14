# BreadMind Core Agent Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BreadMind의 핵심 오케스트레이터를 구축한다 — LLM Provider 추상화, Tool Registry, Safety Guard, Core Agent 루프, Working Memory를 포함하여 CLI에서 대화할 수 있는 최소 동작 가능 에이전트를 만든다.

**Architecture:** 모듈러 모놀리스. asyncio 기반 Python 앱. LLM Provider ABC로 모델 교체 가능. Tool Registry가 빌트인 도구와 MCP 도구를 통합 관리. Safety Guard가 모든 tool 실행 전 검사.

**Tech Stack:** Python 3.12+, asyncio, asyncpg, PostgreSQL (pgvector + Apache AGE), anthropic SDK, pydantic, pytest, Docker Compose

**Spec:** `docs/specs/2026-03-14-breadmind-design.md`

---

## Chunk 1: Project Scaffolding & Database

### Task 1: Project Setup

**Files:**
- Create: `pyproject.toml`
- Create: `src/breadmind/__init__.py`
- Create: `src/breadmind/main.py`
- Create: `Dockerfile`
- Create: `docker-compose.yaml`
- Create: `docker/postgres/Dockerfile`
- Create: `config/config.yaml`
- Create: `config/safety.yaml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "breadmind"
version = "0.1.0"
description = "AI Infrastructure Agent for K8s, Proxmox, OpenWrt"
requires-python = ">=3.12"
dependencies = [
    "anthropic>=0.40.0",
    "openai>=1.50.0",
    "asyncpg>=0.30.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.6.0",
    "pyyaml>=6.0",
    "aiohttp>=3.11.0",
    "fastapi>=0.115.0",
    "uvicorn>=0.32.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=6.0",
]

[project.scripts]
breadmind = "breadmind.main:main"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create package init**

```python
# src/breadmind/__init__.py
__version__ = "0.1.0"
```

- [ ] **Step 3: Create main.py stub**

```python
# src/breadmind/main.py
import asyncio

async def run():
    print("BreadMind starting...")

def main():
    asyncio.run(run())

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create Docker files**

```dockerfile
# docker/postgres/Dockerfile
FROM pgvector/pgvector:pg17
RUN apt-get update && apt-get install -y \
    build-essential \
    libreadline-dev \
    zlib1g-dev \
    flex \
    bison \
    git \
    postgresql-server-dev-17 \
    && git clone https://github.com/apache/age.git /tmp/age \
    && cd /tmp/age \
    && make install \
    && rm -rf /tmp/age \
    && apt-get purge -y build-essential git \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
COPY init.sql /docker-entrypoint-initdb.d/
```

```sql
-- docker/postgres/init.sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT create_graph('breadmind_kg');
```

```dockerfile
# Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .
COPY config/ config/
CMD ["breadmind"]
```

```yaml
# docker-compose.yaml
services:
  breadmind:
    build: .
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
    ports: ["8080:8080"]
    volumes:
      - ./config:/app/config
  postgres:
    build: ./docker/postgres
    volumes: ["pgdata:/var/lib/postgresql/data"]
    environment:
      POSTGRES_DB: breadmind
      POSTGRES_USER: breadmind
      POSTGRES_PASSWORD: ${DB_PASSWORD:-breadmind_dev}
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U breadmind"]
      interval: 5s
      timeout: 5s
      retries: 5
volumes:
  pgdata:
```

- [ ] **Step 5: Create config files**

```yaml
# config/config.yaml
llm:
  default_provider: claude
  default_model: claude-sonnet-4-6
  fallback_chain: [claude, ollama]
  tool_call_max_turns: 10
  tool_call_timeout_seconds: 30

providers:
  claude:
    type: api
    api_key: ${ANTHROPIC_API_KEY}
  ollama:
    type: ollama
    base_url: http://localhost:11434

auth:
  messenger:
    slack:
      allowed_users: []
    discord:
      allowed_users: []
    telegram:
      allowed_users: []

database:
  host: ${DB_HOST:-localhost}
  port: ${DB_PORT:-5432}
  name: ${DB_NAME:-breadmind}
  user: ${DB_USER:-breadmind}
  password: ${DB_PASSWORD:-breadmind_dev}
```

```yaml
# config/safety.yaml
blacklist:
  kubernetes:
    - k8s_delete_namespace
    - k8s_drain_node
    - k8s_delete_pv
  proxmox:
    - pve_delete_vm
    - pve_delete_storage
    - pve_format_disk
  openwrt:
    - owrt_factory_reset
    - owrt_firmware_upgrade

require_approval:
  - mcp_install
  - mcp_uninstall
  - pve_create_vm
  - k8s_apply_manifest
  - shell_exec
```

- [ ] **Step 6: Create test conftest**

```python
# tests/__init__.py
```

```python
# tests/conftest.py
import pytest

@pytest.fixture
def safety_config():
    return {
        "blacklist": {
            "test": ["dangerous_action"]
        },
        "require_approval": ["needs_approval"]
    }
```

- [ ] **Step 7: Install and verify**

Run: `cd /d/Projects/breadmind && pip install -e ".[dev]"`
Expected: Successful installation

- [ ] **Step 8: Run smoke test**

Run: `cd /d/Projects/breadmind && python -m breadmind.main`
Expected: "BreadMind starting..."

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: project scaffolding with Docker, config, and test setup"
```

---

### Task 2: Database Layer

**Files:**
- Create: `src/breadmind/storage/__init__.py`
- Create: `src/breadmind/storage/database.py`
- Create: `src/breadmind/storage/models.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_storage.py
import pytest
from breadmind.storage.models import AuditEntry, EpisodicNote
from datetime import datetime

def test_audit_entry_creation():
    entry = AuditEntry(
        action="k8s_list_pods",
        params={"namespace": "default"},
        result="ALLOWED",
        reason="auto-allow",
        channel="slack",
        user="U12345",
    )
    assert entry.action == "k8s_list_pods"
    assert entry.result == "ALLOWED"

def test_episodic_note_creation():
    note = EpisodicNote(
        content="User prefers snapshots before VM changes",
        keywords=["snapshot", "vm", "preference"],
        tags=["user_preference", "proxmox"],
        context_description="Learned from conversation about VM management",
    )
    assert "snapshot" in note.keywords
    assert note.embedding is None  # not yet computed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Projects/breadmind && pytest tests/test_storage.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Write models**

```python
# src/breadmind/storage/__init__.py
```

```python
# src/breadmind/storage/models.py
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class AuditEntry:
    action: str
    params: dict
    result: str  # ALLOWED / DENIED / APPROVED / REJECTED
    reason: str
    channel: str
    user: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    id: int | None = None

@dataclass
class EpisodicNote:
    content: str
    keywords: list[str]
    tags: list[str]
    context_description: str
    embedding: list[float] | None = None
    linked_note_ids: list[int] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    id: int | None = None
```

- [ ] **Step 4: Write database.py**

```python
# src/breadmind/storage/database.py
import asyncpg
from contextlib import asynccontextmanager

class Database:
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self):
        self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=10)
        await self._migrate()

    async def disconnect(self):
        if self._pool:
            await self._pool.close()

    @asynccontextmanager
    async def acquire(self):
        async with self._pool.acquire() as conn:
            yield conn

    async def _migrate(self):
        async with self.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ DEFAULT NOW(),
                    action TEXT NOT NULL,
                    params JSONB DEFAULT '{}',
                    result TEXT NOT NULL,
                    reason TEXT DEFAULT '',
                    channel TEXT DEFAULT '',
                    "user" TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS episodic_notes (
                    id SERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    keywords TEXT[] DEFAULT '{}',
                    tags TEXT[] DEFAULT '{}',
                    context_description TEXT DEFAULT '',
                    embedding vector(384),
                    linked_note_ids INTEGER[] DEFAULT '{}',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS mcp_servers (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    install_config JSONB NOT NULL,
                    status TEXT DEFAULT 'stopped',
                    installed_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)

    async def insert_audit(self, entry) -> int:
        async with self.acquire() as conn:
            return await conn.fetchval("""
                INSERT INTO audit_log (action, params, result, reason, channel, "user")
                VALUES ($1, $2::jsonb, $3, $4, $5, $6)
                RETURNING id
            """, entry.action, str(entry.params), entry.result,
                entry.reason, entry.channel, entry.user)

    async def health_check(self) -> bool:
        try:
            async with self.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False
```

- [ ] **Step 5: Run tests**

Run: `cd /d/Projects/breadmind && pytest tests/test_storage.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: database layer with models, migrations, and audit log"
```

---

## Chunk 2: LLM Provider Abstraction

### Task 3: LLM Base Types

**Files:**
- Create: `src/breadmind/llm/__init__.py`
- Create: `src/breadmind/llm/base.py`
- Test: `tests/test_llm_base.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_llm_base.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Projects/breadmind && pytest tests/test_llm_base.py -v`
Expected: FAIL

- [ ] **Step 3: Write base types**

```python
# src/breadmind/llm/__init__.py
```

```python
# src/breadmind/llm/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Any

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int

@dataclass
class LLMMessage:
    role: str  # "user" | "assistant" | "system" | "tool"
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # for tool result messages
    name: str | None = None  # tool name for tool results

@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    usage: TokenUsage
    stop_reason: str

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema

class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...
```

- [ ] **Step 4: Run tests**

Run: `cd /d/Projects/breadmind && pytest tests/test_llm_base.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: LLM provider base types and abstract interface"
```

---

### Task 4: Claude API Provider

**Files:**
- Create: `src/breadmind/llm/claude.py`
- Test: `tests/test_llm_claude.py`

- [ ] **Step 1: Write failing test (mocked)**

```python
# tests/test_llm_claude.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from breadmind.llm.claude import ClaudeProvider
from breadmind.llm.base import LLMMessage, ToolDefinition

@pytest.fixture
def claude_provider():
    return ClaudeProvider(api_key="test-key", default_model="claude-sonnet-4-6")

@pytest.mark.asyncio
async def test_claude_chat_text_response(claude_provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="Hello from Claude")]
    mock_response.stop_reason = "end_turn"
    mock_response.usage = MagicMock(input_tokens=10, output_tokens=5)

    with patch.object(
        claude_provider._client.messages,
        "create",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        result = await claude_provider.chat(
            messages=[LLMMessage(role="user", content="hi")],
        )
    assert result.content == "Hello from Claude"
    assert result.has_tool_calls is False

@pytest.mark.asyncio
async def test_claude_chat_tool_call(claude_provider):
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = "tc_1"
    tool_block.name = "k8s_list_pods"
    tool_block.input = {"namespace": "default"}

    mock_response = MagicMock()
    mock_response.content = [tool_block]
    mock_response.stop_reason = "tool_use"
    mock_response.usage = MagicMock(input_tokens=10, output_tokens=20)

    with patch.object(
        claude_provider._client.messages,
        "create",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        tool_def = ToolDefinition(
            name="k8s_list_pods",
            description="List pods",
            parameters={"type": "object", "properties": {}},
        )
        result = await claude_provider.chat(
            messages=[LLMMessage(role="user", content="list pods")],
            tools=[tool_def],
        )
    assert result.has_tool_calls is True
    assert result.tool_calls[0].name == "k8s_list_pods"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Projects/breadmind && pytest tests/test_llm_claude.py -v`
Expected: FAIL

- [ ] **Step 3: Implement ClaudeProvider**

```python
# src/breadmind/llm/claude.py
import anthropic
from .base import (
    LLMProvider, LLMResponse, LLMMessage,
    ToolCall, TokenUsage, ToolDefinition,
)

class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, default_model: str = "claude-sonnet-4-6"):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._default_model = default_model

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        api_messages = self._convert_messages(messages)
        kwargs = {
            "model": model or self._default_model,
            "max_tokens": 4096,
            "messages": api_messages,
        }
        if tools:
            kwargs["tools"] = [self._convert_tool(t) for t in tools]

        response = await self._client.messages.create(**kwargs)
        return self._parse_response(response)

    async def health_check(self) -> bool:
        try:
            await self._client.messages.create(
                model=self._default_model,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception:
            return False

    def _convert_messages(self, messages: list[LLMMessage]) -> list[dict]:
        result = []
        for msg in messages:
            if msg.role == "system":
                continue  # handled separately
            if msg.role == "tool":
                result.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content or "",
                    }],
                })
            elif msg.tool_calls:
                result.append({
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
                        for tc in msg.tool_calls
                    ],
                })
            else:
                result.append({"role": msg.role, "content": msg.content or ""})
        return result

    def _convert_tool(self, tool: ToolDefinition) -> dict:
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.parameters,
        }

    def _parse_response(self, response) -> LLMResponse:
        content = None
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content = block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
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
```

- [ ] **Step 4: Run tests**

Run: `cd /d/Projects/breadmind && pytest tests/test_llm_claude.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: Claude API provider with tool calling support"
```

---

### Task 5: Ollama Provider

**Files:**
- Create: `src/breadmind/llm/ollama.py`
- Test: `tests/test_llm_ollama.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_llm_ollama.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from breadmind.llm.ollama import OllamaProvider
from breadmind.llm.base import LLMMessage

@pytest.fixture
def ollama_provider():
    return OllamaProvider(base_url="http://localhost:11434", default_model="llama3")

@pytest.mark.asyncio
async def test_ollama_chat(ollama_provider):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "message": {"role": "assistant", "content": "Hello"},
        "done": True,
        "eval_count": 5,
        "prompt_eval_count": 10,
    })
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await ollama_provider.chat(
            messages=[LLMMessage(role="user", content="hi")]
        )
    assert result.content == "Hello"
    assert result.has_tool_calls is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Projects/breadmind && pytest tests/test_llm_ollama.py -v`
Expected: FAIL

- [ ] **Step 3: Implement OllamaProvider**

```python
# src/breadmind/llm/ollama.py
import aiohttp
import json
from .base import (
    LLMProvider, LLMResponse, LLMMessage,
    ToolCall, TokenUsage, ToolDefinition,
)

class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str = "http://localhost:11434", default_model: str = "llama3"):
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        payload = {
            "model": model or self._default_model,
            "messages": [{"role": m.role, "content": m.content or ""} for m in messages],
            "stream": False,
        }
        if tools:
            payload["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools
            ]

        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self._base_url}/api/chat", json=payload) as resp:
                data = await resp.json()

        msg = data.get("message", {})
        tool_calls = []
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            tool_calls.append(ToolCall(
                id=fn.get("name", ""),
                name=fn.get("name", ""),
                arguments=fn.get("arguments", {}),
            ))

        return LLMResponse(
            content=msg.get("content"),
            tool_calls=tool_calls,
            usage=TokenUsage(
                input_tokens=data.get("prompt_eval_count", 0),
                output_tokens=data.get("eval_count", 0),
            ),
            stop_reason="tool_use" if tool_calls else "end_turn",
        )

    async def health_check(self) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self._base_url}/api/tags") as resp:
                    return resp.status == 200
        except Exception:
            return False
```

- [ ] **Step 4: Run tests**

Run: `cd /d/Projects/breadmind && pytest tests/test_llm_ollama.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: Ollama provider for local LLM support"
```

---

### Task 6: CLI Provider (claude -p, gemini, codex)

**Files:**
- Create: `src/breadmind/llm/cli.py`
- Test: `tests/test_llm_cli.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_llm_cli.py
import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from breadmind.llm.cli import CLIProvider
from breadmind.llm.base import LLMMessage

@pytest.fixture
def cli_provider():
    return CLIProvider(command="claude", args=["-p"], name="claude-cli")

@pytest.mark.asyncio
async def test_cli_provider_text_response(cli_provider):
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"Hello from CLI", b""))
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await cli_provider.chat(
            messages=[LLMMessage(role="user", content="hi")]
        )
    assert result.content == "Hello from CLI"
    assert result.has_tool_calls is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Projects/breadmind && pytest tests/test_llm_cli.py -v`
Expected: FAIL

- [ ] **Step 3: Implement CLIProvider**

```python
# src/breadmind/llm/cli.py
import asyncio
import json
from .base import (
    LLMProvider, LLMResponse, LLMMessage,
    ToolCall, TokenUsage, ToolDefinition,
)

class CLIProvider(LLMProvider):
    """Subprocess-based provider for CLI tools (claude -p, gemini, codex).
    Personal/local use only. See Anthropic ToS for usage policy."""

    def __init__(self, command: str, args: list[str] | None = None, name: str = "cli"):
        self._command = command
        self._args = args or []
        self._name = name

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        prompt = self._build_prompt(messages, tools)
        proc = await asyncio.create_subprocess_exec(
            self._command, *self._args, prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace").strip()

        tool_calls = []
        content = output
        if tools:
            parsed = self._try_parse_tool_calls(output)
            if parsed:
                tool_calls = parsed
                content = None

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=TokenUsage(input_tokens=0, output_tokens=0),
            stop_reason="tool_use" if tool_calls else "end_turn",
        )

    async def health_check(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._command, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == 0
        except FileNotFoundError:
            return False

    def _build_prompt(self, messages: list[LLMMessage], tools: list[ToolDefinition] | None) -> str:
        parts = []
        if tools:
            tool_descriptions = json.dumps(
                [{"name": t.name, "description": t.description, "parameters": t.parameters} for t in tools],
                indent=2,
            )
            parts.append(f"Available tools:\n{tool_descriptions}\n")
            parts.append("If you need to use a tool, respond ONLY with JSON: {\"tool_calls\": [{\"name\": \"...\", \"arguments\": {...}}]}\n")
        for msg in messages:
            if msg.role != "system":
                parts.append(f"{msg.role}: {msg.content}")
        return "\n".join(parts)

    def _try_parse_tool_calls(self, output: str) -> list[ToolCall] | None:
        try:
            data = json.loads(output)
            if "tool_calls" in data:
                return [
                    ToolCall(id=f"cli_{i}", name=tc["name"], arguments=tc.get("arguments", {}))
                    for i, tc in enumerate(data["tool_calls"])
                ]
        except (json.JSONDecodeError, KeyError):
            pass
        return None
```

- [ ] **Step 4: Run tests**

Run: `cd /d/Projects/breadmind && pytest tests/test_llm_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: CLI provider for claude -p, gemini, codex subprocess calls"
```

---

## Chunk 3: Tool Registry & Safety Guard

### Task 7: Tool Registry

**Files:**
- Create: `src/breadmind/tools/__init__.py`
- Create: `src/breadmind/tools/registry.py`
- Create: `src/breadmind/tools/builtin.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_tools.py
import pytest
from breadmind.tools.registry import ToolRegistry, tool
from breadmind.llm.base import ToolDefinition

@tool(description="Echo the input message back")
async def echo(message: str) -> str:
    """Echo tool for testing."""
    return f"echo: {message}"

def test_tool_decorator_creates_definition():
    assert hasattr(echo, "_tool_definition")
    defn = echo._tool_definition
    assert defn.name == "echo"
    assert "message" in defn.parameters.get("properties", {})

def test_registry_register_and_list():
    registry = ToolRegistry()
    registry.register(echo)
    tools = registry.get_all_definitions()
    assert len(tools) == 1
    assert tools[0].name == "echo"

@pytest.mark.asyncio
async def test_registry_execute():
    registry = ToolRegistry()
    registry.register(echo)
    result = await registry.execute("echo", {"message": "hello"})
    assert result.success is True
    assert result.output == "echo: hello"

@pytest.mark.asyncio
async def test_registry_execute_unknown_tool():
    registry = ToolRegistry()
    result = await registry.execute("nonexistent", {})
    assert result.success is False
    assert "not found" in result.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Projects/breadmind && pytest tests/test_tools.py -v`
Expected: FAIL

- [ ] **Step 3: Implement ToolRegistry**

```python
# src/breadmind/tools/__init__.py
```

```python
# src/breadmind/tools/registry.py
import inspect
import asyncio
from dataclasses import dataclass
from typing import Any, Callable
from breadmind.llm.base import ToolDefinition

@dataclass
class ToolResult:
    success: bool
    output: str

def tool(description: str):
    """Decorator to register a function as an agent tool."""
    def decorator(func: Callable):
        sig = inspect.signature(func)
        properties = {}
        required = []
        for name, param in sig.parameters.items():
            prop = {"type": "string"}
            annotation = param.annotation
            if annotation == int:
                prop = {"type": "integer"}
            elif annotation == float:
                prop = {"type": "number"}
            elif annotation == bool:
                prop = {"type": "boolean"}
            properties[name] = prop
            if param.default is inspect.Parameter.empty:
                required.append(name)

        func._tool_definition = ToolDefinition(
            name=func.__name__,
            description=description,
            parameters={
                "type": "object",
                "properties": properties,
                "required": required,
            },
        )
        return func
    return decorator

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Callable] = {}
        self._definitions: dict[str, ToolDefinition] = {}

    def register(self, func: Callable):
        defn = getattr(func, "_tool_definition", None)
        if defn is None:
            raise ValueError(f"{func.__name__} is not decorated with @tool")
        self._tools[defn.name] = func
        self._definitions[defn.name] = defn

    def get_all_definitions(self) -> list[ToolDefinition]:
        return list(self._definitions.values())

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        func = self._tools.get(name)
        if func is None:
            return ToolResult(success=False, output=f"Tool not found: {name}")
        try:
            if asyncio.iscoroutinefunction(func):
                output = await func(**arguments)
            else:
                output = func(**arguments)
            return ToolResult(success=True, output=str(output))
        except Exception as e:
            return ToolResult(success=False, output=f"Tool error: {e}")
```

- [ ] **Step 4: Run tests**

Run: `cd /d/Projects/breadmind && pytest tests/test_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: tool registry with decorator-based registration and execution"
```

---

### Task 8: Safety Guard

**Files:**
- Create: `src/breadmind/core/__init__.py`
- Create: `src/breadmind/core/safety.py`
- Test: `tests/test_safety.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_safety.py
import pytest
from breadmind.core.safety import SafetyGuard, SafetyResult

@pytest.fixture
def guard():
    return SafetyGuard(
        blacklist={"test": ["dangerous_action"]},
        require_approval=["needs_approval"],
    )

def test_auto_allow(guard):
    result = guard.check("safe_action", {}, user="test_user", channel="test")
    assert result == SafetyResult.ALLOW

def test_blacklist_deny(guard):
    result = guard.check("dangerous_action", {}, user="test_user", channel="test")
    assert result == SafetyResult.DENY

def test_require_approval(guard):
    result = guard.check("needs_approval", {}, user="test_user", channel="test")
    assert result == SafetyResult.REQUIRE_APPROVAL

def test_flatten_blacklist(guard):
    assert "dangerous_action" in guard._flat_blacklist
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Projects/breadmind && pytest tests/test_safety.py -v`
Expected: FAIL

- [ ] **Step 3: Implement SafetyGuard**

```python
# src/breadmind/core/__init__.py
```

```python
# src/breadmind/core/safety.py
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime

class SafetyResult(Enum):
    ALLOW = "ALLOWED"
    DENY = "DENIED"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"

class SafetyGuard:
    def __init__(
        self,
        blacklist: dict[str, list[str]] | None = None,
        require_approval: list[str] | None = None,
    ):
        self._blacklist = blacklist or {}
        self._require_approval = set(require_approval or [])
        self._flat_blacklist = set()
        for actions in self._blacklist.values():
            self._flat_blacklist.update(actions)
        self._cooldowns: dict[str, datetime] = {}

    def check(self, action: str, params: dict, user: str, channel: str) -> SafetyResult:
        if action in self._flat_blacklist:
            return SafetyResult.DENY
        if action in self._require_approval:
            return SafetyResult.REQUIRE_APPROVAL
        return SafetyResult.ALLOW

    def check_cooldown(self, target: str, action: str, cooldown_minutes: int = 10) -> bool:
        """Returns True if action is allowed (not in cooldown)."""
        key = f"{target}:{action}"
        now = datetime.utcnow()
        last = self._cooldowns.get(key)
        if last and (now - last).total_seconds() < cooldown_minutes * 60:
            return False
        self._cooldowns[key] = now
        return True
```

- [ ] **Step 4: Run tests**

Run: `cd /d/Projects/breadmind && pytest tests/test_safety.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: safety guard with blacklist, approval, and cooldown"
```

---

## Chunk 4: Core Agent Orchestrator

### Task 9: Core Agent Loop

**Files:**
- Create: `src/breadmind/core/agent.py`
- Test: `tests/test_agent.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_agent.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.core.agent import CoreAgent
from breadmind.llm.base import LLMResponse, LLMMessage, ToolCall, TokenUsage
from breadmind.tools.registry import ToolRegistry, ToolResult, tool
from breadmind.core.safety import SafetyGuard

@tool(description="Test tool")
async def test_tool(input: str) -> str:
    return f"result: {input}"

@pytest.fixture
def agent():
    registry = ToolRegistry()
    registry.register(test_tool)
    provider = AsyncMock()
    guard = SafetyGuard()
    return CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
    )

@pytest.mark.asyncio
async def test_agent_text_response(agent):
    agent._provider.chat = AsyncMock(return_value=LLMResponse(
        content="Hello!",
        tool_calls=[],
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    ))
    result = await agent.handle_message("hi", user="test", channel="test")
    assert result == "Hello!"

@pytest.mark.asyncio
async def test_agent_tool_call_loop(agent):
    # First call returns tool_call, second call returns text
    agent._provider.chat = AsyncMock(side_effect=[
        LLMResponse(
            content=None,
            tool_calls=[ToolCall(id="tc1", name="test_tool", arguments={"input": "hello"})],
            usage=TokenUsage(input_tokens=10, output_tokens=20),
            stop_reason="tool_use",
        ),
        LLMResponse(
            content="Done! Result was: result: hello",
            tool_calls=[],
            usage=TokenUsage(input_tokens=30, output_tokens=10),
            stop_reason="end_turn",
        ),
    ])
    result = await agent.handle_message("use the tool", user="test", channel="test")
    assert "Done!" in result
    assert agent._provider.chat.call_count == 2

@pytest.mark.asyncio
async def test_agent_max_turns_limit(agent):
    # Always returns tool_call — should stop at max_turns
    agent._provider.chat = AsyncMock(return_value=LLMResponse(
        content=None,
        tool_calls=[ToolCall(id="tc1", name="test_tool", arguments={"input": "loop"})],
        usage=TokenUsage(input_tokens=10, output_tokens=20),
        stop_reason="tool_use",
    ))
    agent._max_turns = 3
    result = await agent.handle_message("loop forever", user="test", channel="test")
    assert "max" in result.lower() or agent._provider.chat.call_count == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /d/Projects/breadmind && pytest tests/test_agent.py -v`
Expected: FAIL

- [ ] **Step 3: Implement CoreAgent**

```python
# src/breadmind/core/agent.py
from breadmind.llm.base import LLMProvider, LLMMessage, LLMResponse, ToolCall
from breadmind.tools.registry import ToolRegistry
from breadmind.core.safety import SafetyGuard, SafetyResult

class CoreAgent:
    def __init__(
        self,
        provider: LLMProvider,
        tool_registry: ToolRegistry,
        safety_guard: SafetyGuard,
        system_prompt: str = "You are BreadMind, an AI infrastructure agent.",
        max_turns: int = 10,
    ):
        self._provider = provider
        self._tools = tool_registry
        self._guard = safety_guard
        self._system_prompt = system_prompt
        self._max_turns = max_turns

    async def handle_message(self, message: str, user: str, channel: str) -> str:
        messages = [
            LLMMessage(role="system", content=self._system_prompt),
            LLMMessage(role="user", content=message),
        ]
        tools = self._tools.get_all_definitions()

        for turn in range(self._max_turns):
            response = await self._provider.chat(messages=messages, tools=tools or None)

            if not response.has_tool_calls:
                return response.content or ""

            # Process tool calls
            for tc in response.tool_calls:
                safety = self._guard.check(tc.name, tc.arguments, user=user, channel=channel)

                if safety == SafetyResult.DENY:
                    messages.append(LLMMessage(
                        role="assistant", tool_calls=[tc],
                    ))
                    messages.append(LLMMessage(
                        role="tool", content=f"BLOCKED: {tc.name} is in the blacklist.",
                        tool_call_id=tc.id, name=tc.name,
                    ))
                    continue

                if safety == SafetyResult.REQUIRE_APPROVAL:
                    messages.append(LLMMessage(
                        role="assistant", tool_calls=[tc],
                    ))
                    messages.append(LLMMessage(
                        role="tool",
                        content=f"PENDING_APPROVAL: {tc.name} requires user approval. Inform the user.",
                        tool_call_id=tc.id, name=tc.name,
                    ))
                    continue

                # Execute tool
                result = await self._tools.execute(tc.name, tc.arguments)
                messages.append(LLMMessage(
                    role="assistant", tool_calls=[tc],
                ))
                messages.append(LLMMessage(
                    role="tool", content=result.output,
                    tool_call_id=tc.id, name=tc.name,
                ))

        return "Maximum tool call turns reached. Please try a simpler request."
```

- [ ] **Step 4: Run tests**

Run: `cd /d/Projects/breadmind && pytest tests/test_agent.py -v`
Expected: PASS

- [ ] **Step 5: Run all tests**

Run: `cd /d/Projects/breadmind && pytest -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: core agent orchestrator with tool call loop and safety guard"
```

---

### Task 10: Wire Up Main Entry Point

**Files:**
- Modify: `src/breadmind/main.py`
- Create: `src/breadmind/config.py`

- [ ] **Step 1: Create config loader**

```python
# src/breadmind/config.py
import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class LLMConfig:
    default_provider: str = "claude"
    default_model: str = "claude-sonnet-4-6"
    fallback_chain: list[str] = field(default_factory=lambda: ["claude", "ollama"])
    tool_call_max_turns: int = 10
    tool_call_timeout_seconds: int = 30

@dataclass
class DatabaseConfig:
    host: str = "localhost"
    port: int = 5432
    name: str = "breadmind"
    user: str = "breadmind"
    password: str = "breadmind_dev"

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

@dataclass
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)

def load_config(config_dir: str = "config") -> AppConfig:
    config_path = Path(config_dir) / "config.yaml"
    if not config_path.exists():
        return AppConfig()

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    # Expand env vars
    raw = _expand_env(raw)

    llm_raw = raw.get("llm", {})
    db_raw = raw.get("database", {})

    return AppConfig(
        llm=LLMConfig(**{k: v for k, v in llm_raw.items() if k in LLMConfig.__dataclass_fields__}),
        database=DatabaseConfig(**{k: v for k, v in db_raw.items() if k in DatabaseConfig.__dataclass_fields__}),
    )

def _expand_env(obj):
    if isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
        var = obj[2:-1]
        default = None
        if ":-" in var:
            var, default = var.split(":-", 1)
        return os.environ.get(var, default or "")
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env(v) for v in obj]
    return obj

def load_safety_config(config_dir: str = "config") -> dict:
    safety_path = Path(config_dir) / "safety.yaml"
    if not safety_path.exists():
        return {"blacklist": {}, "require_approval": []}
    with open(safety_path) as f:
        return yaml.safe_load(f) or {}
```

- [ ] **Step 2: Update main.py with interactive CLI loop**

```python
# src/breadmind/main.py
import asyncio
import sys
from breadmind.config import load_config, load_safety_config
from breadmind.core.agent import CoreAgent
from breadmind.core.safety import SafetyGuard
from breadmind.llm.claude import ClaudeProvider
from breadmind.llm.ollama import OllamaProvider
from breadmind.tools.registry import ToolRegistry

def create_provider(config):
    provider_name = config.llm.default_provider
    providers_cfg = {}  # TODO: load from config.yaml providers section
    if provider_name == "claude":
        import os
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            print("Warning: ANTHROPIC_API_KEY not set, falling back to ollama")
            return OllamaProvider()
        return ClaudeProvider(api_key=api_key, default_model=config.llm.default_model)
    elif provider_name == "ollama":
        return OllamaProvider()
    else:
        return OllamaProvider()

async def run():
    config = load_config()
    safety_cfg = load_safety_config()

    provider = create_provider(config)
    registry = ToolRegistry()
    guard = SafetyGuard(
        blacklist=safety_cfg.get("blacklist", {}),
        require_approval=safety_cfg.get("require_approval", []),
    )

    agent = CoreAgent(
        provider=provider,
        tool_registry=registry,
        safety_guard=guard,
        max_turns=config.llm.tool_call_max_turns,
    )

    print("BreadMind v0.1.0 - AI Infrastructure Agent")
    print("Type 'quit' to exit.\n")

    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input or user_input.lower() in ("quit", "exit"):
            break

        response = await agent.handle_message(user_input, user="local", channel="cli")
        print(f"breadmind> {response}\n")

def main():
    asyncio.run(run())

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run all tests**

Run: `cd /d/Projects/breadmind && pytest -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat: config loader and interactive CLI entry point"
```

- [ ] **Step 5: Push to GitHub**

```bash
cd /d/Projects/breadmind && git push origin master
```

---

## Summary

| Task | Component | Status |
|------|-----------|--------|
| 1 | Project scaffolding, Docker, config | `- [ ]` |
| 2 | Database layer (models, migrations) | `- [ ]` |
| 3 | LLM base types and ABC | `- [ ]` |
| 4 | Claude API Provider | `- [ ]` |
| 5 | Ollama Provider | `- [ ]` |
| 6 | CLI Provider (claude -p, gemini, codex) | `- [ ]` |
| 7 | Tool Registry with decorator | `- [ ]` |
| 8 | Safety Guard | `- [ ]` |
| 9 | Core Agent orchestrator loop | `- [ ]` |
| 10 | Config loader + CLI entry point | `- [ ]` |

**Next sub-projects (separate plans):**
- Sub-project 2: MCP Client + Infrastructure Adapters
- Sub-project 3: Monitoring Engine
- Sub-project 4: Messenger Gateway (Slack/Discord/Telegram)
- Sub-project 5: Web Dashboard + Memory System (Episodic + KG)
