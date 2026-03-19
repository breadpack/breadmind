# Coding Agent Delegation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `code_delegate` tool that delegates coding tasks to Claude Code, Codex, and Gemini CLI via local subprocess or SSH.

**Architecture:** Adapter pattern for CLI differences, Executor pattern for local/remote, session tracking via DB.

**Tech Stack:** Python 3.12+, asyncio, asyncssh (existing)

**Spec:** `docs/superpowers/specs/2026-03-19-coding-agent-delegation-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `src/breadmind/coding/__init__.py` | Package init |
| `src/breadmind/coding/adapters/__init__.py` | Adapter registry |
| `src/breadmind/coding/adapters/base.py` | `CodingAgentAdapter` ABC, `CodingResult` dataclass |
| `src/breadmind/coding/adapters/claude_code.py` | Claude Code CLI adapter |
| `src/breadmind/coding/adapters/codex.py` | Codex CLI adapter |
| `src/breadmind/coding/adapters/gemini_cli.py` | Gemini CLI adapter |
| `src/breadmind/coding/executors/__init__.py` | Package init |
| `src/breadmind/coding/executors/base.py` | `Executor` ABC, `ExecutionResult` dataclass |
| `src/breadmind/coding/executors/local.py` | `LocalExecutor` (subprocess) |
| `src/breadmind/coding/executors/remote.py` | `RemoteExecutor` (SSH) |
| `src/breadmind/coding/session_store.py` | `CodingSessionStore` |
| `src/breadmind/coding/project_config.py` | `ProjectConfigManager` |
| `src/breadmind/coding/tool.py` | `code_delegate` tool registration |
| `tests/test_coding_delegate.py` | All tests |

### Modified Files
| File | Change |
|------|--------|
| `config/safety.yaml` | Add `code_delegate` to `require_approval` |

---

## Task 1: Base interfaces (adapters + executors)

**Files:**
- Create: `src/breadmind/coding/__init__.py`
- Create: `src/breadmind/coding/adapters/__init__.py`
- Create: `src/breadmind/coding/adapters/base.py`
- Create: `src/breadmind/coding/executors/__init__.py`
- Create: `src/breadmind/coding/executors/base.py`
- Test: `tests/test_coding_delegate.py`

- [ ] **Step 1: Write failing test for CodingResult and ExecutionResult**

```python
# tests/test_coding_delegate.py
from breadmind.coding.adapters.base import CodingAgentAdapter, CodingResult
from breadmind.coding.executors.base import Executor, ExecutionResult


def test_coding_result_defaults():
    r = CodingResult(success=True, output="done", files_changed=["a.py"])
    assert r.success is True
    assert r.session_id is None
    assert r.agent == ""


def test_execution_result():
    r = ExecutionResult(stdout="ok", stderr="", returncode=0)
    assert r.returncode == 0
```

- [ ] **Step 2: Implement base interfaces**

`adapters/base.py`:
```python
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

@dataclass
class CodingResult:
    success: bool
    output: str
    files_changed: list[str]
    cost: dict | None = None
    execution_time: float = 0.0
    agent: str = ""
    session_id: str | None = None

class CodingAgentAdapter(ABC):
    name: str = ""
    cli_command: str = ""
    config_filename: str = ""

    @abstractmethod
    def build_command(self, project: str, prompt: str, options: dict | None = None) -> list[str]: ...

    @abstractmethod
    def parse_result(self, stdout: str, stderr: str, returncode: int) -> CodingResult: ...
```

`executors/base.py`:
```python
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    returncode: int

class Executor(ABC):
    @abstractmethod
    async def run(self, command: list[str], cwd: str, timeout: int = 300) -> ExecutionResult: ...
```

- [ ] **Step 3: Run tests, verify pass**
- [ ] **Step 4: Commit**

```bash
git commit -m "feat(coding): add base interfaces for coding agent delegation"
```

---

## Task 2: Three CLI adapters

**Files:**
- Create: `src/breadmind/coding/adapters/claude_code.py`
- Create: `src/breadmind/coding/adapters/codex.py`
- Create: `src/breadmind/coding/adapters/gemini_cli.py`
- Modify: `src/breadmind/coding/adapters/__init__.py`
- Test: `tests/test_coding_delegate.py`

- [ ] **Step 1: Write failing tests for each adapter's build_command and parse_result**

```python
from breadmind.coding.adapters.claude_code import ClaudeCodeAdapter
from breadmind.coding.adapters.codex import CodexAdapter
from breadmind.coding.adapters.gemini_cli import GeminiCLIAdapter


def test_claude_build_command():
    a = ClaudeCodeAdapter()
    cmd = a.build_command("/project", "add login")
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "add login" in cmd
    assert "--cwd" in cmd
    assert "/project" in cmd


def test_claude_build_command_with_session():
    a = ClaudeCodeAdapter()
    cmd = a.build_command("/project", "continue work", {"session_id": "abc123"})
    assert "--resume" in cmd
    assert "abc123" in cmd


def test_claude_parse_result_success():
    a = ClaudeCodeAdapter()
    r = a.parse_result('{"result":"done","session_id":"s1"}', "", 0)
    assert r.success is True
    assert r.session_id == "s1"


def test_codex_build_command():
    a = CodexAdapter()
    cmd = a.build_command("/project", "refactor")
    assert cmd[0] == "codex"
    assert "--prompt" in cmd


def test_gemini_build_command():
    a = GeminiCLIAdapter()
    cmd = a.build_command("/project", "add tests")
    assert cmd[0] == "gemini"
    assert "-p" in cmd


def test_adapter_registry():
    from breadmind.coding.adapters import get_adapter
    assert get_adapter("claude").name == "claude"
    assert get_adapter("codex").name == "codex"
    assert get_adapter("gemini").name == "gemini"
```

- [ ] **Step 2: Implement 3 adapters + registry**

Each adapter implements `build_command()` and `parse_result()` per CLI mapping table in spec.

`adapters/__init__.py`:
```python
from breadmind.coding.adapters.claude_code import ClaudeCodeAdapter
from breadmind.coding.adapters.codex import CodexAdapter
from breadmind.coding.adapters.gemini_cli import GeminiCLIAdapter

_ADAPTERS = {
    "claude": ClaudeCodeAdapter(),
    "codex": CodexAdapter(),
    "gemini": GeminiCLIAdapter(),
}

def get_adapter(name: str):
    if name not in _ADAPTERS:
        raise ValueError(f"Unknown coding agent: {name}. Available: {list(_ADAPTERS.keys())}")
    return _ADAPTERS[name]
```

- [ ] **Step 3: Run tests, verify pass**
- [ ] **Step 4: Commit**

```bash
git commit -m "feat(coding): add Claude Code, Codex, Gemini CLI adapters"
```

---

## Task 3: Local and Remote executors

**Files:**
- Create: `src/breadmind/coding/executors/local.py`
- Create: `src/breadmind/coding/executors/remote.py`
- Test: `tests/test_coding_delegate.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from breadmind.coding.executors.local import LocalExecutor

@pytest.mark.asyncio
async def test_local_executor_runs_command():
    executor = LocalExecutor()
    result = await executor.run(["echo", "hello"], cwd=".", timeout=10)
    assert result.returncode == 0
    assert "hello" in result.stdout

@pytest.mark.asyncio
async def test_local_executor_timeout():
    executor = LocalExecutor()
    with pytest.raises(asyncio.TimeoutError):
        await executor.run(["sleep", "10"], cwd=".", timeout=1)

@pytest.mark.asyncio
async def test_local_executor_command_not_found():
    executor = LocalExecutor()
    result = await executor.run(["nonexistent_cmd_xyz"], cwd=".", timeout=5)
    assert result.returncode != 0
```

- [ ] **Step 2: Implement LocalExecutor and RemoteExecutor**

`local.py`: `asyncio.create_subprocess_exec` + `wait_for` timeout + process kill on timeout.

`remote.py`: `asyncssh.connect()` + `run()` + `credential_ref` resolve via CredentialVault. Handle connection failure gracefully.

- [ ] **Step 3: Run tests, verify pass**
- [ ] **Step 4: Commit**

```bash
git commit -m "feat(coding): add Local and Remote executors"
```

---

## Task 4: Session store and project config

**Files:**
- Create: `src/breadmind/coding/session_store.py`
- Create: `src/breadmind/coding/project_config.py`
- Test: `tests/test_coding_delegate.py`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_session_store_save_and_get():
    store = CodingSessionStore(db=None)  # In-memory fallback
    await store.save_session("/project", "claude", "s1", "Added login feature")
    session = await store.get_last_session("/project", "claude")
    assert session == "s1"

def test_project_config_paths():
    mgr = ProjectConfigManager()
    assert mgr.get_config_path("/project", "claude").name == "CLAUDE.md"
    assert mgr.get_config_path("/project", "codex").name == "AGENTS.md"
    assert mgr.get_config_path("/project", "gemini").name == "GEMINI.md"
```

- [ ] **Step 2: Implement session store (DB + in-memory fallback) and project config manager**
- [ ] **Step 3: Run tests, verify pass**
- [ ] **Step 4: Commit**

```bash
git commit -m "feat(coding): add session store and project config manager"
```

---

## Task 5: code_delegate tool

**Files:**
- Create: `src/breadmind/coding/tool.py`
- Create: `src/breadmind/coding/__init__.py` (update exports)
- Modify: `config/safety.yaml` — add `code_delegate` to `require_approval`
- Test: `tests/test_coding_delegate.py`

- [ ] **Step 1: Write failing test for tool registration and execution**

```python
@pytest.mark.asyncio
async def test_code_delegate_tool_exists():
    from breadmind.coding.tool import create_code_delegate_tool
    tool_def, tool_fn = create_code_delegate_tool()
    assert tool_def.name == "code_delegate"
    assert "agent" in [p.name for p in tool_def.parameters]

@pytest.mark.asyncio
async def test_code_delegate_invalid_agent():
    from breadmind.coding.tool import create_code_delegate_tool
    _, tool_fn = create_code_delegate_tool()
    result = await tool_fn(agent="invalid", project="/tmp", prompt="test")
    assert not result.success
    assert "Unknown" in result.output
```

- [ ] **Step 2: Implement code_delegate tool**

`tool.py` orchestrates: validate params → get_adapter → build_command → choose executor → run → parse_result → save session → return ToolResult.

- [ ] **Step 3: Add `code_delegate` to safety.yaml require_approval**
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(coding): add code_delegate tool with safety integration"
```

---

## Task 6: Tool registration in bootstrap + intent detection

**Files:**
- Modify: `src/breadmind/core/bootstrap.py` — register `code_delegate` tool
- Modify: `src/breadmind/core/intent.py` — add `coding` category keywords

- [ ] **Step 1: Register code_delegate in bootstrap tool registry**

In `init_agent()`, after other tool registrations:
```python
from breadmind.coding.tool import create_code_delegate_tool
tool_def, tool_fn = create_code_delegate_tool(db=db)
registry.register_from_definition(tool_def, tool_fn)
```

- [ ] **Step 2: Add coding keywords to intent classifier**

Add Korean/English coding keywords: "코드", "구현", "리팩토링", "버그 수정", "테스트 작성", "code", "implement", "refactor", "fix bug", "write test" etc.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(coding): register code_delegate tool and add coding intent detection"
```

---

## Task 7: Integration test and final cleanup

**Files:**
- Modify: `tests/test_coding_delegate.py`

- [ ] **Step 1: Add integration test that mocks CLI execution**

```python
@pytest.mark.asyncio
async def test_full_delegation_flow_mocked():
    """Mock subprocess to simulate Claude Code CLI execution."""
    # Mock LocalExecutor to return successful result
    # Call code_delegate tool
    # Verify CodingResult is correct
    # Verify session is saved
```

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ -v`

- [ ] **Step 3: Commit**

```bash
git commit -m "test(coding): add integration test for delegation flow"
```
