# BreadMind Plugin System

## Overview

Claude Code 플러그인 포맷을 네이티브로 채택하여, Claude Code 플러그인을 변환 없이 그대로 사용하고 BreadMind 전용 확장은 `x-breadmind` 네임스페이스로 추가한다. 마켓플레이스를 통해 플러그인 검색/설치/관리가 가능하다.

## Design Decisions

- **Claude Code 플러그인 포맷 100% 호환**: `plugin.json`, `commands/`, `skills/`, `agents/`, `hooks/` 구조를 그대로 사용
- **변환 레이어 불필요**: 동일한 포맷이므로 별도 변환 없이 직접 로드
- **BreadMind 확장**: `x-breadmind` 네임스페이스로 코딩 에이전트, Swarm 역할, MCP 서버 등 추가 기능 선언
- **2 Phase 구현**: Phase 1 (플러그인 시스템 코어) → Phase 2 (마켓플레이스)

## Architecture

### 디렉토리 구조

```
~/.breadmind/plugins/
├── installed/
│   ├── aider-adapter/
│   │   ├── .claude-plugin/
│   │   │   └── plugin.json
│   │   ├── commands/
│   │   │   └── aider-run.md
│   │   ├── skills/
│   │   │   └── aider-workflow.md
│   │   ├── agents/
│   │   │   └── code-reviewer.md
│   │   └── hooks/
│   │       └── hooks.json
│   │
│   └── k8s-toolkit/
│       ├── .claude-plugin/
│       │   └── plugin.json
│       ├── commands/
│       ├── skills/
│       └── roles/              # x-breadmind 확장
│           └── helm_expert.j2
│
└── registry.json               # 설치된 플러그인 인덱스
```

### 소스 코드 구조

```
src/breadmind/plugins/
├── __init__.py
├── manager.py          # PluginManager — 로드/활성화/비활성화/제거
├── manifest.py         # PluginManifest — plugin.json 파싱 + 검증
├── loader.py           # PluginLoader — 컴포넌트별 로드 (commands, skills, agents, hooks)
├── registry.py         # PluginRegistry — 설치된 플러그인 인덱스 관리
└── marketplace.py      # MarketplaceClient — 원격 레지스트리 검색/설치
```

## Plugin Manifest (plugin.json)

Claude Code 표준 필드 + BreadMind 확장:

```json
{
  "name": "aider-adapter",
  "version": "1.0.0",
  "description": "Aider AI coding assistant integration",
  "author": "community",

  "commands": "commands/",
  "skills": "skills/",
  "agents": "agents/",
  "hooks": "hooks/",

  "x-breadmind": {
    "coding_agents": [
      {
        "name": "aider",
        "cli_command": "aider",
        "prompt_flag": "--message",
        "cwd_flag": "--cwd",
        "output_format": "text",
        "config_filename": ".aider.conf.yml",
        "session_flag": "--session-id"
      }
    ],
    "roles": ["roles/helm_expert.j2"],
    "mcp_servers": ".mcp.json",
    "tools": [
      {
        "name": "helm_deploy",
        "handler": "tools/helm_deploy.py",
        "description": "Deploy Helm chart",
        "require_approval": true
      }
    ],
    "requires": {
      "cli": ["aider"],
      "breadmind": ">=0.2.0"
    },
    "settings": {
      "model": {"type": "string", "default": "gpt-4o", "description": "Default model"},
      "auto_commit": {"type": "boolean", "default": true, "description": "Auto-commit changes"}
    }
  }
}
```

## Component Loading

### Commands (commands/*.md)

Claude Code 슬래시 커맨드와 동일한 포맷. YAML frontmatter + 마크다운 본문.

BreadMind에서의 처리:
- 커맨드 이름을 BreadMind 도구로 등록
- 사용자가 호출하면 마크다운 프롬프트를 LLM에 주입하여 실행

### Skills (skills/*.md)

프롬프트 템플릿. BreadMind의 behaviors/fragments 시스템과 통합:
- 스킬 이름으로 참조 가능
- `PromptBuilder`의 `custom_instructions`에 주입 가능

### Agents (agents/*.md)

서브에이전트 정의. BreadMind의 Swarm 역할과 통합:
- 에이전트 프롬프트를 SwarmMember.system_prompt로 변환
- delegate_tasks에서 활용 가능

### Hooks (hooks/hooks.json)

이벤트 기반 자동화. BreadMind의 EventBus와 매핑:

| Claude Code Hook | BreadMind EventBus |
|---|---|
| PreToolUse | EventType.TOOL_PRE_EXECUTE |
| PostToolUse | EventType.TOOL_POST_EXECUTE |
| SessionStart | EventType.SESSION_START |
| Stop | EventType.SESSION_END |

### Coding Agents (x-breadmind.coding_agents)

`code_delegate` 어댑터 자동 등록. 선언적 CLI 매핑으로 Python 코드 없이 새 에이전트 추가 가능.

### Roles (x-breadmind.roles)

Jinja2 역할 템플릿. `PromptBuilder`의 roles 디렉토리에 추가.

### Tools (x-breadmind.tools)

Python 도구 핸들러. ToolRegistry에 등록. `require_approval` 지원.

## PluginManager API

```python
class PluginManager:
    def __init__(self, plugins_dir: Path, tool_registry, prompt_builder, event_bus, db=None):
        ...

    async def discover(self) -> list[PluginManifest]:
        """installed/ 디렉토리에서 plugin.json 검색"""

    async def load(self, plugin_name: str) -> Plugin:
        """플러그인 로드 및 활성화
        - commands → ToolRegistry에 프롬프트 기반 도구로 등록
        - skills → PromptBuilder fragments로 등록
        - agents → SwarmManager 역할로 등록
        - hooks → EventBus 리스너로 등록
        - x-breadmind.coding_agents → AdapterRegistry에 등록
        - x-breadmind.roles → PromptBuilder roles에 추가
        - x-breadmind.tools → ToolRegistry에 등록
        - x-breadmind.mcp_servers → MCP 매니저에 등록
        """

    async def unload(self, plugin_name: str):
        """플러그인 비활성화 (모든 등록 해제)"""

    async def install(self, source: str) -> PluginManifest:
        """설치: git clone / 로컬 복사 / 마켓플레이스 다운로드"""

    async def uninstall(self, plugin_name: str):
        """제거: 디렉토리 삭제 + 등록 해제"""

    async def load_all(self):
        """부팅 시 모든 활성 플러그인 로드"""

    def get_settings(self, plugin_name: str) -> dict:
        """플러그인 설정 조회"""

    async def update_settings(self, plugin_name: str, settings: dict):
        """플러그인 설정 업데이트 (DB 저장)"""
```

## Marketplace

### 레지스트리 소스

```json
{
  "registries": [
    {"name": "breadmind-official", "url": "https://plugins.breadmind.dev/registry.json"},
    {"name": "community", "url": "https://github.com/breadmind-plugins/registry/raw/main/registry.json"},
    {"name": "claude-plugins", "url": "https://registry.claude.com/plugins.json"}
  ]
}
```

### 레지스트리 포맷

```json
{
  "plugins": [
    {
      "name": "aider-adapter",
      "version": "1.0.0",
      "description": "Aider integration",
      "author": "community",
      "source": "https://github.com/breadmind-plugins/aider-adapter",
      "type": "coding-agent",
      "tags": ["coding", "aider", "ai-assistant"],
      "downloads": 1234,
      "stars": 56
    }
  ]
}
```

### MarketplaceClient

```python
class MarketplaceClient:
    async def search(self, query: str, tags: list[str] = None) -> list[dict]: ...
    async def get_info(self, plugin_name: str) -> dict: ...
    async def install(self, plugin_name: str, target_dir: Path) -> Path: ...
    async def check_updates(self) -> list[dict]: ...
```

### 설치 소스 지원

| 소스 | 예시 |
|------|------|
| 마켓플레이스 | `breadmind plugin install aider-adapter` |
| Git URL | `breadmind plugin install https://github.com/user/my-plugin` |
| 로컬 경로 | `breadmind plugin install ./my-plugin` |
| Claude Code 플러그인 디렉토리 | `breadmind plugin install ~/.claude/plugins/superpowers` |

## Web UI Integration

### Settings > Plugins 페이지

```
Installed
├── [toggle] aider-adapter v1.0.0 — Aider integration [Settings] [Uninstall]
├── [toggle] k8s-toolkit v2.1.0 — K8s helpers [Settings] [Uninstall]
└── [toggle] claude-superpowers v5.0.2 — Imported from Claude Code [Settings] [Uninstall]

Browse Marketplace
├── [search bar] [category filter]
├── aider-adapter ★56 ↓1234 — Aider integration [Install]
├── cursor-adapter ★23 ↓567 — Cursor integration [Install]
└── ...
```

### Web API

```
GET  /api/plugins                    # 설치된 플러그인 목록
GET  /api/plugins/:name              # 플러그인 상세 정보
POST /api/plugins/install            # 설치 {source: "..."}
POST /api/plugins/:name/enable       # 활성화
POST /api/plugins/:name/disable      # 비활성화
DELETE /api/plugins/:name            # 제거
GET  /api/plugins/:name/settings     # 설정 조회
POST /api/plugins/:name/settings     # 설정 업데이트
GET  /api/marketplace/search         # 마켓 검색 {q: "...", tags: [...]}
GET  /api/marketplace/info/:name     # 마켓 플러그인 상세
POST /api/marketplace/install/:name  # 마켓에서 설치
```

## CLI Integration

```bash
breadmind plugin list                              # 설치된 플러그인 목록
breadmind plugin install <source>                  # 설치
breadmind plugin uninstall <name>                  # 제거
breadmind plugin enable/disable <name>             # 활성화/비활성화
breadmind plugin search <query>                    # 마켓 검색
breadmind plugin update [name]                     # 업데이트
```

## Integration with Existing Systems

| 기존 시스템 | 통합 방법 |
|-----------|----------|
| ToolRegistry | 플러그인 도구/커맨드 → `register()` |
| PromptBuilder | 플러그인 스킬/역할 → fragments/roles 추가 |
| SwarmManager | 플러그인 에이전트 → SwarmMember 역할 추가 |
| EventBus | 플러그인 훅 → 이벤트 리스너 등록 |
| AdapterRegistry | 플러그인 coding_agents → `code_delegate` 어댑터 등록 |
| MCP Manager | 플러그인 mcp_servers → MCP 서버 등록 |
| SafetyGuard | 플러그인 도구 → require_approval 적용 |
| AuditLogger | 모든 플러그인 도구 호출 자동 기록 |
| bootstrap.py | 부팅 시 `PluginManager.load_all()` 호출 |

## Coding Adapter Migration

기존 하드코딩된 3개 어댑터를 내장 플러그인으로 전환:

```
src/breadmind/coding/adapters/  (하드코딩)
  → ~/.breadmind/plugins/builtin/coding-agents/
      ├── .claude-plugin/plugin.json
      └── (코딩 에이전트 선언만, Python 코드 없음)
```

`plugin.json`:
```json
{
  "name": "builtin-coding-agents",
  "version": "0.2.1",
  "description": "Built-in coding agent adapters (Claude Code, Codex, Gemini CLI)",
  "author": "breadmind",
  "x-breadmind": {
    "coding_agents": [
      {"name": "claude", "cli_command": "claude", "prompt_flag": "-p", "cwd_flag": "--cwd", "output_format": "json", "config_filename": "CLAUDE.md", "session_flag": "--resume"},
      {"name": "codex", "cli_command": "codex", "prompt_flag": "--prompt", "cwd_flag": "--cwd", "output_format": "text", "config_filename": "AGENTS.md", "session_flag": "--session"},
      {"name": "gemini", "cli_command": "gemini", "prompt_flag": "-p", "cwd_flag": "--cwd", "output_format": "json", "config_filename": "GEMINI.md", "session_flag": "--session"}
    ]
  }
}
```

이로써 `src/breadmind/coding/adapters/` 하드코딩 제거 → 선언적 plugin.json으로 대체. code_delegate 도구는 AdapterRegistry에서 선언적으로 등록된 어댑터를 조회.

## Safety & Security

- 플러그인 Python 도구는 샌드박싱 없이 실행 (호스트 신뢰 모델)
- 모든 플러그인 도구는 SafetyGuard를 통과
- `require_approval: true`인 도구는 사용자 승인 필수
- 마켓 설치 시 매니페스트 검증 (필수 필드 확인)
- 플러그인 설정은 DB에 저장 (비밀번호 등은 credential_ref 사용)

## Implementation Phases

### Phase 1: 플러그인 시스템 코어
- PluginManifest 파싱
- PluginManager (discover, load, unload, install from local/git)
- PluginLoader (commands, skills, agents, hooks, x-breadmind 컴포넌트)
- 선언적 코딩 에이전트 어댑터 (하드코딩 어댑터 대체)
- 부팅 시 자동 로드
- 웹 API (설치/활성화/비활성화/설정)

### Phase 2: 마켓플레이스
- MarketplaceClient (원격 레지스트리 검색/설치)
- 웹 UI Browse 탭
- CLI `breadmind plugin search/install`
- 업데이트 확인

## Dependencies

신규 의존성 없음. `aiohttp` (기존), `asyncio`, `json`, `pathlib` 활용.
