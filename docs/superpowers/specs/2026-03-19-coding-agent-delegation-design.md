# Coding Agent Delegation

## Overview

BreadMind가 외부 코딩 에이전트(Claude Code, Codex, Gemini CLI)에 코딩 작업을 위임하는 오케스트레이터 기능. 채팅 자동 감지 + `code_delegate` 명시적 도구 양방향 진입점을 제공하며, 로컬 subprocess와 SSH 원격 실행을 모두 지원한다.

## Architecture

### 컴포넌트 구조

```
src/breadmind/coding/
├── __init__.py
├── adapters/
│   ├── __init__.py
│   ├── base.py              # CodingAgentAdapter ABC, CodingResult dataclass
│   ├── claude_code.py       # Claude Code CLI 어댑터
│   ├── codex.py             # OpenAI Codex CLI 어댑터
│   └── gemini_cli.py        # Gemini CLI 어댑터
├── executors/
│   ├── __init__.py
│   ├── base.py              # Executor ABC, ExecutionResult dataclass
│   ├── local.py             # LocalExecutor (subprocess)
│   └── remote.py            # RemoteExecutor (SSH via asyncssh)
├── session_store.py         # 프로젝트별 세션 추적
├── project_config.py        # 프로젝트별 설정 파일 관리 (CLAUDE.md 등)
└── tool.py                  # code_delegate 도구 등록
```

### 데이터 흐름

```
사용자 요청 (채팅 자동 감지 or 명시적 도구)
  → SafetyGuard 검사 (승인 필요 도구)
  → AuditLogger 기록
  → CodingAgentAdapter 선택 (claude/codex/gemini)
  → 프로젝트 설정 파일 확인
  → CLI 명령 조합
  → Executor 선택 (local/remote)
  → 실행 + stdout/stderr 캡처 + 타임아웃 관리
  → CodingResult 파싱
  → 세션 ID 저장
  → 사용자에게 결과 보고
```

## Core Interfaces

### CodingAgentAdapter

```python
class CodingAgentAdapter(ABC):
    name: str                    # "claude", "codex", "gemini"
    cli_command: str             # "claude", "codex", "gemini"
    config_filename: str         # "CLAUDE.md", "AGENTS.md", "GEMINI.md"

    @abstractmethod
    def build_command(self, project: str, prompt: str, options: dict | None = None) -> list[str]: ...

    @abstractmethod
    def parse_result(self, stdout: str, stderr: str, returncode: int) -> CodingResult: ...
```

### CodingResult

```python
@dataclass
class CodingResult:
    success: bool
    output: str
    files_changed: list[str]
    cost: dict | None = None
    execution_time: float = 0.0
    agent: str = ""
    session_id: str | None = None
```

### Executor

```python
class Executor(ABC):
    @abstractmethod
    async def run(self, command: list[str], cwd: str, timeout: int = 300) -> ExecutionResult: ...

@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    returncode: int
```

## CLI Mapping

| 항목 | Claude Code | Codex | Gemini CLI |
|------|------------|-------|------------|
| CLI 명령 | `claude` | `codex` | `gemini` |
| 프롬프트 | `-p "prompt"` | `--prompt "prompt"` | `-p "prompt"` |
| 작업 디렉토리 | `--cwd /path` | `--cwd /path` | `--cwd /path` |
| 비대화 모드 | `--output-format json` | `--quiet` | `--output-format json` |
| 설정 파일 | `CLAUDE.md` | `AGENTS.md` | `GEMINI.md` |
| 모델 지정 | `--model opus` | `--model o3` | `--model gemini-2.5-pro` |
| 세션 이어가기 | `--continue` / `--resume <id>` | `--session <id>` | `--continue` / `--session <id>` |

## Session Management

```python
class CodingSessionStore:
    """프로젝트별 코딩 에이전트 세션 추적. DB settings 테이블에 저장."""
    async def save_session(self, project: str, agent: str, session_id: str, summary: str): ...
    async def get_last_session(self, project: str, agent: str) -> str | None: ...
    async def list_sessions(self, project: str) -> list[dict]: ...
```

## code_delegate Tool

```python
@tool(
    name="code_delegate",
    description="Delegate a coding task to an external coding agent (Claude Code, Codex, Gemini CLI).",
    parameters={
        "agent": {"type": "string", "enum": ["claude", "codex", "gemini"], "description": "Which coding agent to use"},
        "project": {"type": "string", "description": "Absolute path to the project directory"},
        "prompt": {"type": "string", "description": "The coding task to delegate"},
        "model": {"type": "string", "description": "Model override (optional)"},
        "session_id": {"type": "string", "description": "Resume a previous session (optional)"},
        "remote": {"type": "object", "description": "SSH remote execution config: {host, username} (optional, null=local)"},
        "timeout": {"type": "integer", "description": "Timeout in seconds (default: 300)"},
    },
    required=["agent", "project", "prompt"],
)
```

## Chat Auto-Detection

Intent classifier에 `coding` 카테고리 추가. 코딩 관련 키워드 감지 시 `code_delegate` 도구를 자동으로 선택하도록 도구 설명에 코딩 키워드 포함.

## Executor Details

### LocalExecutor
- `asyncio.create_subprocess_exec()` 사용
- stdout/stderr 캡처
- `asyncio.wait_for()` 타임아웃

### RemoteExecutor
- 기존 `asyncssh` 의존성 활용
- `credential_ref` 토큰 지원 (CredentialVault 연동)
- SSH 미접속 시 `[REQUEST_INPUT]` 폼으로 자격증명 수집

## Error Handling

| 상황 | 처리 |
|------|------|
| 타임아웃 (기본 5분) | 프로세스 kill → 타임아웃 보고 |
| CLI 미설치 | `FileNotFoundError` → "{agent} CLI가 설치되지 않았습니다" |
| SSH 접속 실패 | `[REQUEST_INPUT]` 폼 or 에러 보고 |
| 에이전트 비정상 종료 | stderr 내용 보고 |
| 프로젝트 경로 없음 | 에러 보고 |

## Safety

- `code_delegate`는 `safety.yaml`의 `require_approval` 목록에 추가 — 사용자 승인 후 실행
- 원격 실행 시 자격증명은 `credential_ref` 토큰으로만 처리

## Project Config Management

```python
class ProjectConfigManager:
    """프로젝트별 에이전트 설정 파일 관리"""
    def ensure_config(self, project: str, agent: str) -> Path | None:
        """에이전트별 설정 파일이 있으면 경로 반환, 없으면 None"""
        ...
    def get_config_path(self, project: str, agent: str) -> Path:
        """CLAUDE.md, AGENTS.md, GEMINI.md 경로"""
        ...
```

## Integration Points

| 기존 시스템 | 통합 방법 |
|-----------|----------|
| ToolRegistry | `code_delegate` 도구 등록 |
| SafetyGuard | `require_approval` 목록에 추가 |
| AuditLogger | 도구 호출 자동 기록 |
| Intent Classifier | `coding` 카테고리 추가 |
| BehaviorTracker | 코딩 위임 결과도 분석 대상 |

## Dependencies

신규 의존성 없음. 기존 `asyncssh`, `asyncio` 활용.
