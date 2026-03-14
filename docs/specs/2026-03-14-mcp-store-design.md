# MCP Store 설계 스펙

**Date:** 2026-03-14
**Status:** Approved

## 1. 개요

웹 대시보드에 MCP Store 탭을 추가하여 MCP 서버를 검색, 설치, 관리할 수 있는 마켓플레이스를 제공한다. 설치 과정에서 LLM이 자동 구성, 대화형 안내, 트러블슈팅을 지원한다.

## 2. UI 구조

### 2.1 탭 배치

```
Chat | Monitoring | MCP Store | Settings
```

### 2.2 MCP Store 레이아웃

```
┌─────────────────────────────────────────────────────┐
│ 🔍 [검색바: "Search MCP servers..."]    [Search]     │
├───────────────────────┬─────────────────────────────┤
│ 검색 결과 / 설치됨    │  설치 대화 패널              │
│                       │  (Install Assistant)         │
│ ┌─────────────────┐   │                             │
│ │ 서버 카드        │   │  Phase 1: 자동 구성 분석    │
│ │ name, desc      │   │  Phase 2: 환경변수 수집     │
│ │ source, runtime │   │  Phase 3: 설치 + 로그       │
│ │ [Install]       │   │                             │
│ └─────────────────┘   │  ┌─────────────────────┐    │
│                       │  │ LLM 대화 메시지      │    │
│ ┌─────────────────┐   │  │ + 인라인 입력 필드   │    │
│ │ 설치된 서버      │   │  └─────────────────────┘    │
│ │ status: running │   │                             │
│ │ [Stop] [Remove] │   │  [실시간 설치 로그]          │
│ └─────────────────┘   │                             │
└───────────────────────┴─────────────────────────────┘
```

- 왼쪽: 검색 결과 + 설치된 서버 목록 (토글)
- 오른쪽: 설치 어시스턴트 대화 패널 (Install 클릭 시 활성화)

## 3. 설치 워크플로우

### 3.1 Phase 1 — 자동 구성 분석

Install 버튼 클릭 시:
1. 서버 메타데이터(name, description, install_command, source)를 LLM에 전달
2. LLM이 분석하여 구조화된 JSON 반환:
   ```json
   {
     "runtime": "node",
     "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-github"],
     "required_env": [
       {"name": "GITHUB_TOKEN", "description": "GitHub Personal Access Token", "secret": true}
     ],
     "optional_env": [],
     "dependencies": ["node>=18"],
     "summary": "GitHub MCP 서버입니다. GitHub API에 접근하기 위해 Personal Access Token이 필요합니다."
   }
   ```
3. 분석 결과를 대화 패널에 요약 표시

### 3.2 Phase 2 — 대화형 환경변수 수집

1. required_env의 각 항목을 순서대로 안내
2. 대화 패널에 인라인 입력 필드 표시 (secret=true면 password 타입)
3. 사용자 입력 완료 시 Phase 3으로 진행
4. optional_env는 "건너뛰기" 가능

### 3.3 Phase 3 — 설치 실행 + 트러블슈팅

1. 의존성 확인 (runtime 설치 여부 체크)
2. MCP 서버 프로세스 시작 (MCPClientManager.start_stdio_server)
3. 실시간 로그를 WebSocket으로 스트리밍
4. 성공 시: 도구 목록 표시 + DB에 서버 정보 저장
5. 실패 시:
   - 에러 로그를 LLM에 전달
   - LLM이 원인 분석 + 해결책 제시
   - "npm이 설치되지 않았습니다. 설치할까요?" → 사용자 확인 후 자동 설치 시도
   - 재시도 버튼 제공

## 4. 백엔드 API

### 4.1 검색

```
GET /api/mcp/search?q={query}&limit={10}
Response: { results: [{ name, slug, description, source, install_command }] }
```

### 4.2 설치 분석 (LLM)

```
POST /api/mcp/install/analyze
Body: { name, slug, description, source, install_command }
Response: { runtime, command, args, required_env, optional_env, dependencies, summary }
```

LLM에 서버 메타데이터를 보내고 구조화된 설치 가이드를 생성.

### 4.3 설치 실행

```
POST /api/mcp/install/execute
Body: { name, slug, command, args, env: {KEY: value}, source }
Response: { status: "started", server_name }
```

설치 진행 상황은 `/ws/chat` WebSocket으로 `{type: "install_log", ...}` 이벤트 전송.

### 4.4 트러블슈팅 (LLM)

```
POST /api/mcp/install/troubleshoot
Body: { server_name, error_log, context }
Response: { analysis, suggestion, auto_fix_available, fix_command }
```

### 4.5 서버 관리

```
POST /api/mcp/servers/{name}/start
POST /api/mcp/servers/{name}/stop
DELETE /api/mcp/servers/{name}
GET /api/mcp/servers/{name}/tools
```

## 5. DB 영속화

기존 `mcp_servers` 테이블 활용:
```sql
-- 이미 존재하는 테이블
CREATE TABLE IF NOT EXISTS mcp_servers (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    install_config JSONB NOT NULL,  -- {command, args, env, runtime, source, slug}
    status TEXT DEFAULT 'stopped',
    installed_at TIMESTAMPTZ DEFAULT NOW()
);
```

- 설치 시 install_config에 실행에 필요한 모든 정보 저장
- 환경변수(API 키 등)는 Fernet 암호화 후 install_config.env에 저장
- 서버 시작 시 DB에서 config 로드 → 복호화 → 프로세스 시작
- BreadMind 재시작 시 status='running'인 서버 자동 복구

## 6. LLM 통합

### 6.1 경량 LLM 호출

CoreAgent의 도구 호출 루프를 사용하지 않고, 직접 LLM API 호출:

```python
class InstallAssistant:
    def __init__(self, provider: LLMProvider):
        self._provider = provider

    async def analyze(self, server_meta: dict) -> dict:
        """Phase 1: 서버 메타데이터 분석"""
        prompt = ANALYZE_PROMPT.format(**server_meta)
        response = await self._provider.chat([
            LLMMessage(role="system", content=INSTALL_SYSTEM_PROMPT),
            LLMMessage(role="user", content=prompt),
        ])
        return json.loads(response.content)

    async def troubleshoot(self, error_log: str, context: dict) -> dict:
        """Phase 3: 에러 분석 + 해결책"""
        prompt = TROUBLESHOOT_PROMPT.format(error=error_log, **context)
        response = await self._provider.chat([
            LLMMessage(role="system", content=INSTALL_SYSTEM_PROMPT),
            LLMMessage(role="user", content=prompt),
        ])
        return json.loads(response.content)
```

### 6.2 시스템 프롬프트

```
You are an MCP server installation assistant.
Analyze server metadata and provide structured installation guidance.
Always respond in valid JSON.
```

## 7. 파일 구조

```
src/breadmind/
├── mcp/
│   ├── install_assistant.py   # LLM 기반 설치 어시스턴트
│   └── store.py               # MCP Store 비즈니스 로직 (검색, 설치, 관리)
├── web/
│   ├── app.py                 # 기존 + MCP Store API 엔드포인트 추가
│   └── static/
│       └── index.html         # MCP Store 탭 UI 추가
```

## 8. 에러 처리

| 시나리오 | 처리 |
|---------|------|
| 레지스트리 검색 실패 | "검색 서비스에 연결할 수 없습니다" 표시, 재시도 버튼 |
| LLM 분석 실패 | 수동 구성 폼으로 폴백 (command, args, env 직접 입력) |
| 의존성 미설치 | LLM이 설치 명령 제안, 사용자 확인 후 실행 |
| MCP 서버 시작 실패 | 에러 로그 → LLM 트러블슈팅 → 해결책 제시 |
| DB 미연결 | 메모리에만 저장 (재시작 시 손실 경고) |
