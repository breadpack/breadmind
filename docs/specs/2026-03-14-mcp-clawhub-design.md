# Sub-project 2: MCP Client + ClawHub + Built-in Tools Design Spec

**Date:** 2026-03-14
**Status:** Approved
**Sub-project:** 2/5 — MCP Client + ClawHub Integration
**Depends on:** Sub-project 1 (Core Agent) — completed

## 1. Overview

BreadMind의 Tool Manager를 구축한다. MCP 프로토콜 클라이언트로 ClawHub 스킬과 외부 MCP 서버를 연결하고, 최소한의 빌트인 도구를 구현하여 에이전트가 실제로 도구를 사용할 수 있게 만든다.

### 목표

- MCP 클라이언트로 stdio/SSE 트랜스포트 지원
- ClawHub 스킬 검색, 설치, 실행 파이프라인
- 설정 가능한 레지스트리 목록 (ClawHub + MCP Registry + 커스텀)
- 빌트인 도구 구현 (shell_exec, web_search, file_read, file_write)
- 기존 ToolRegistry와 통합

### 핵심 결정 사항

| 항목 | 결정 |
|------|------|
| ClawHub 역할 | 보조 도구 소스 (빌트인이 주력) |
| MCP 서버 관리 | 하이브리드: ClawHub=subprocess(stdio), 외부=SSE/HTTP |
| 탐색 소스 | 설정 가능한 레지스트리 목록 (기본: ClawHub + MCP Registry) |
| 보안 정책 | 설치/제거만 승인, 도구 실행은 기존 Safety Guard 규칙 |

## 2. Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Tool Manager                       │
│                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐│
│  │  Built-in    │  │  MCP Client  │  │  Registry   ││
│  │  Tools       │  │  Manager     │  │  Search     ││
│  │ shell_exec   │  │              │  │  Engine     ││
│  │ web_search   │  │ ┌──────────┐ │  │             ││
│  │ file_read    │  │ │ stdio    │ │  │ ClawHub API ││
│  │ file_write   │  │ │(ClawHub) │ │  │ MCP Registry││
│  └──────┬───────┘  │ ├──────────┤ │  │ Custom...   ││
│         │          │ │ SSE/HTTP │ │  └──────┬──────┘│
│         │          │ │(external)│ │         │       │
│         │          │ └──────────┘ │         │       │
│         └────────┬────────┘─────────────────┘       │
│                  ▼                                    │
│         ┌────────────────┐                           │
│         │  ToolRegistry  │  ← Sub-project 1 확장     │
│         │  (unified)     │                           │
│         └────────────────┘                           │
└─────────────────────────────────────────────────────┘
```

## 3. MCP Client Manager

### 3.1 인터페이스

```python
@dataclass
class MCPServerInfo:
    name: str
    transport: str          # "stdio" | "sse"
    status: str             # "running" | "stopped" | "error"
    tools: list[str]        # 제공하는 도구 이름 목록
    source: str             # "clawhub" | "config" | "manual"

class MCPClientManager:
    async def start_stdio_server(self, name: str, command: str,
                                  args: list[str], env: dict[str, str] | None = None) -> None
    async def connect_sse_server(self, name: str, url: str,
                                  headers: dict[str, str] | None = None) -> None
    async def stop_server(self, name: str) -> None
    async def discover_tools(self, name: str) -> list[ToolDefinition]
    async def call_tool(self, server_name: str, tool_name: str,
                         arguments: dict) -> ToolResult
    async def list_servers(self) -> list[MCPServerInfo]
    async def health_check(self, name: str) -> bool
    async def start_all(self) -> None       # config + 설치된 스킬 일괄 시작
    async def stop_all(self) -> None
```

### 3.2 트랜스포트

| 트랜스포트 | 용도 | 구현 |
|-----------|------|------|
| stdio | ClawHub 스킬 (로컬 subprocess) | asyncio.create_subprocess_exec + JSON-RPC over stdin/stdout |
| SSE | 외부 MCP 서버 | aiohttp SSE 클라이언트 + JSON-RPC |

### 3.3 MCP 프로토콜 메시지

JSON-RPC 2.0 기반:
- `initialize` — 핸드셰이크, 프로토콜 버전 협상
- `tools/list` — 서버가 제공하는 도구 목록 조회
- `tools/call` — 도구 실행 요청

### 3.4 생명주기 관리

- BreadMind 시작 시: config의 외부 서버 연결 + 설치된 ClawHub 스킬 자동 시작
- 런타임 중: `mcp_install` → subprocess 시작 → 도구 자동 등록
- MCP 서버 크래시 시: 자동 재시작 (최대 3회), 초과 시 비활성화 + 알림
- BreadMind 종료 시: 모든 subprocess 정리 (stop_all)

### 3.5 설정 (config.yaml 확장)

```yaml
mcp:
  servers:
    my-k8s:
      transport: sse
      url: http://localhost:3001/sse
    my-custom:
      transport: stdio
      command: node
      args: ["./my-mcp-server/index.js"]
      env:
        API_KEY: ${CUSTOM_API_KEY}

  auto_discover: true
  max_restart_attempts: 3

  registries:
    - name: clawhub
      type: clawhub
      enabled: true
    - name: mcp-registry
      type: mcp_registry
      url: https://registry.modelcontextprotocol.io
      enabled: true
```

## 4. Registry Search Engine

### 4.1 인터페이스

```python
@dataclass
class RegistrySearchResult:
    name: str
    slug: str               # 설치용 식별자
    description: str
    source: str              # "clawhub" | "mcp_registry" | 커스텀
    install_command: str | None

class RegistrySearchEngine:
    def __init__(self, registries: list[RegistryConfig])
    async def search(self, query: str, limit: int = 10) -> list[RegistrySearchResult]
    async def get_details(self, slug: str, source: str) -> dict
```

### 4.2 레지스트리 어댑터

| 레지스트리 | API | 검색 방식 |
|-----------|-----|----------|
| ClawHub | HTTP API (clawhub.ai) | 벡터 검색 (임베딩 기반) |
| MCP Registry | HTTP API (registry.modelcontextprotocol.io) | 키워드/카테고리 |
| Custom | 설정된 URL | 레지스트리별 |

검색 시 모든 활성 레지스트리에 병렬 요청 후 결과 병합. 중복은 이름 기반으로 제거.

## 5. Meta Tools (LLM이 호출하는 도구)

| 도구 | 설명 | 승인 필요 |
|------|------|----------|
| `mcp_search` | 레지스트리에서 MCP 스킬 검색 | No |
| `mcp_install` | MCP 스킬 설치 + 시작 | **Yes (항상)** |
| `mcp_uninstall` | MCP 스킬 제거 | **Yes (항상)** |
| `mcp_list` | 설치/연결된 MCP 서버 목록 | No |
| `mcp_start` | 중지된 MCP 서버 시작 | No |
| `mcp_stop` | 실행 중인 MCP 서버 중지 | No |

### 5.1 자동 탐색 흐름

```
사용자: "Proxmox에서 VM 목록 좀 보여줘"
    │
    ▼
LLM: "proxmox 관련 도구가 없음" → mcp_search("proxmox vm management")
    │
    ▼
Registry Search Engine → ClawHub + MCP Registry 병렬 검색
    │
    ▼
LLM → 사용자에게 추천:
  "MCP 서버를 찾았습니다:
   1. mcp-proxmox (ClawHub)
   2. ProxmoxMCP-Plus (MCP Registry)
   설치할까요?"
    │
    ▼
사용자 승인 → mcp_install("mcp-proxmox") → subprocess 시작 → 도구 등록
    │
    ▼
LLM → proxmox_get_vms() 호출 → 결과 반환
```

## 6. Built-in Tools

최소한의 핵심 도구. MCP로 대체 불가능하거나 MCP 없이도 기본 동작해야 하는 것들.

### 6.1 shell_exec

```python
@tool(description="Execute a shell command locally or via SSH")
async def shell_exec(command: str, host: str = "localhost",
                     timeout: int = 30) -> str:
    """Safety Guard에서 require_approval로 분류됨."""
```
- localhost: `asyncio.create_subprocess_exec`
- remote: `asyncssh`로 SSH 실행
- 타임아웃 기본 30초, 설정 가능

### 6.2 web_search

```python
@tool(description="Search the web for information")
async def web_search(query: str, limit: int = 5) -> str:
    """DuckDuckGo API 또는 SearXNG 인스턴스 사용."""
```
- 기본: DuckDuckGo Instant Answer API (무료, API 키 불필요)
- 선택: SearXNG 자체 호스팅 인스턴스 설정 가능

### 6.3 file_read / file_write

```python
@tool(description="Read content from a file")
async def file_read(path: str, encoding: str = "utf-8") -> str:
    """설정 파일 조회 등에 사용."""

@tool(description="Write content to a file")
async def file_write(path: str, content: str, encoding: str = "utf-8") -> str:
    """설정 파일 수정 등에 사용. Safety Guard로 경로 제한 가능."""
```
- 허용 경로를 config로 제한 가능 (보안)

## 7. ToolRegistry 확장

기존 ToolRegistry에 MCP 도구를 통합 등록하는 메서드 추가:

```python
class ToolRegistry:
    # 기존
    def register(self, func: Callable)
    async def execute(self, name: str, arguments: dict) -> ToolResult

    # 신규
    def register_mcp_tool(self, definition: ToolDefinition, server_name: str)
    def unregister_mcp_tools(self, server_name: str)
    def get_tool_source(self, name: str) -> str  # "builtin" | "mcp:<server_name>"
```

execute 시 도구 소스에 따라 분기:
- builtin → 직접 함수 호출 (기존)
- mcp → MCPClientManager.call_tool() 호출

## 8. Safety Guard 통합

- `mcp_install`, `mcp_uninstall`은 safety.yaml의 `require_approval`에 이미 포함
- MCP 도구 실행은 기존 Safety Guard 규칙 그대로 적용
- MCP 서버가 제공하는 도구 이름이 블랙리스트에 포함되면 차단

## 9. DB 확장

기존 `mcp_servers` 테이블 활용 (Sub-project 1에서 이미 생성):

```sql
CREATE TABLE IF NOT EXISTS mcp_servers (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    install_config JSONB NOT NULL,   -- {transport, command, args, env, source, slug}
    status TEXT DEFAULT 'stopped',
    installed_at TIMESTAMPTZ DEFAULT NOW()
);
```

ClawHub 설치 시 이 테이블에 기록, BreadMind 재시작 시 자동 복원.

## 10. Project Structure (신규/수정 파일)

```
src/breadmind/
├── tools/
│   ├── registry.py       # 수정: MCP 도구 통합
│   ├── builtin.py        # 신규: shell_exec, web_search, file_read, file_write
│   ├── mcp_client.py     # 신규: MCPClientManager (stdio + SSE)
│   ├── mcp_protocol.py   # 신규: JSON-RPC 메시지 처리
│   └── registry_search.py # 신규: RegistrySearchEngine (ClawHub + MCP Registry)
├── tools/meta.py          # 신규: mcp_search, mcp_install 등 메타 도구
├── config.py              # 수정: MCP 설정 추가
└── main.py                # 수정: MCP 초기화 추가
```

## 11. Error Handling

| 상황 | 대응 |
|------|------|
| MCP 서버 시작 실패 | 에러 로그 + LLM에 실패 사유 전달 |
| MCP 서버 크래시 | 자동 재시작 (최대 3회), 초과 시 비활성화 + 알림 |
| 도구 호출 타임아웃 | 30초 기본, config 설정 가능. 초과 시 에러 반환 |
| 레지스트리 검색 실패 | 실패한 레지스트리 건너뛰고 성공한 결과만 반환 |
| ClawHub API 불가 | 로컬 설치된 스킬은 정상 동작, 검색만 불가 알림 |

## 12. Tech Stack (추가)

| 영역 | 기술 |
|------|------|
| MCP Protocol | JSON-RPC 2.0 over stdio/SSE |
| HTTP Client | aiohttp (기존 의존성) |
| SSH | asyncssh (shell_exec remote) |
| Web Search | DuckDuckGo API / SearXNG |
