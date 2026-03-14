# BreadMind Design Spec

**Date:** 2026-03-14
**Status:** Approved
**Sub-project:** 1/5 — Core Agent (이 문서는 전체 아키텍처 + Core Agent 설계)

## 1. Overview

BreadMind는 K8s 클러스터, Proxmox 하이퍼바이저, OpenWrt 라우터를 자율적으로 모니터링하고 관리하는 AI 인프라 에이전트이다. Slack, Discord, Telegram, 웹 UI를 통해 자연어로 대화하며, 이상 감지 시 자동으로 대응한다.

### 목표

- 인프라 상태를 주기적으로 모니터링하고 이상 시 자동 대응
- 메신저를 통한 자연어 기반 인프라 관리
- MCP 서버를 자동 탐색/추천/설치하여 도구를 동적으로 확장
- 사용자의 패턴과 선호를 학습하여 점점 더 정확한 판단

### 비목표 (이 서브프로젝트 범위 밖)

- 멀티 테넌시 / 다수 사용자 지원
- 상용 서비스화 (개인 인프라 관리 전용)

## 2. Architecture

### 2.1 모듈러 모놀리스

단일 Python 컨테이너에 모든 기능을 포함하되, 내부를 명확한 모듈로 분리한다. 나중에 필요 시 마이크로서비스로 분리 가능하도록 모듈 간 인터페이스를 정의한다.

### 2.2 모듈 구성

```
┌─────────────────────────────────────────────────────┐
│                   BreadMind                         │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ Messenger│  │  Web UI  │  │   Monitoring      │  │
│  │ Gateway  │  │ (FastAPI)│  │   Engine          │  │
│  │Slack/DC/ │  │          │  │  (APScheduler)    │  │
│  │Telegram  │  │          │  │                   │  │
│  └────┬─────┘  └────┬─────┘  └────────┬──────────┘  │
│       │              │                 │             │
│       └──────────┬───┘─────────────────┘             │
│                  ▼                                    │
│         ┌────────────────┐                           │
│         │   Core Agent   │                           │
│         │  (Orchestrator)│                           │
│         └───┬────────┬───┘                           │
│             │        │                               │
│      ┌──────┘        └──────┐                        │
│      ▼                      ▼                        │
│  ┌────────┐          ┌───────────┐                   │
│  │  LLM   │          │   Tool    │                   │
│  │Provider│          │  Manager  │                   │
│  │Abstract│          │ MCP+Built │                   │
│  └────────┘          └───────────┘                   │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │ Memory   │  │ Safety   │  │  Event   │          │
│  │ System   │  │ Guard    │  │  Log     │          │
│  │(3-layer) │  │(Blacklist│  │          │          │
│  └──────────┘  └──────────┘  └──────────┘          │
│                                                      │
│  ┌──────────────────────────────────────┐           │
│  │          PostgreSQL                   │           │
│  │   pgvector + Apache AGE               │           │
│  └──────────────────────────────────────┘           │
└─────────────────────────────────────────────────────┘
```

| 모듈 | 역할 |
|------|------|
| Core Agent | LLM에 메시지를 보내고 tool calling 결과를 실행하는 오케스트레이터 |
| LLM Provider | Claude/OpenAI/Ollama/CLI 교체 가능한 LLM 인터페이스 |
| Tool Manager | MCP Registry 탐색 + MCP Runtime + 빌트인 도구 통합 관리 |
| Messenger Gateway | Slack/Discord/Telegram 봇 + 메시지 라우팅 |
| Web UI | FastAPI + WebSocket 실시간 대시보드 |
| Monitoring Engine | 주기적 상태 수집 + 규칙 기반 이상 감지 → Core Agent 전달 |
| Safety Guard | 블랙리스트 액션 차단, 승인 필수 액션 관리, 감사 로그 |
| Memory System | 3계층 메모리 (Working + Episodic + Semantic KG) |
| Event Log | 모든 액션/판단의 감사 로그 |

## 3. Core Agent

### 3.1 처리 루프

```
입력 (메시지/이벤트)
        │
        ▼
  Context Builder ← Memory System에서 관련 기억 + 사용자 프로필 로드
        │
        ▼
  LLM Call (streaming) ← system prompt + tools + context
        │
        ▼
    tool_call 있음?
     ├─ Yes → Safety Guard 검사
     │         ├─ 허용 → Tool Manager 실행 → 결과를 LLM에 재전달 (루프)
     │         ├─ 승인 필요 → 사용자에게 승인 요청 → 대기
     │         └─ 차단 → 차단 사유를 LLM에 전달
     │
     └─ No → 응답을 요청 채널로 전송
```

### 3.2 핵심 설계 결정

| 항목 | 결정 |
|------|------|
| Tool 정의 | Python 함수를 데코레이터로 등록, 자동으로 LLM tool schema 생성 |
| 멀티턴 루프 | LLM이 tool_call을 멈출 때까지 반복 (최대 10회 제한) |
| 동시성 | asyncio 기반, 여러 채널의 요청을 동시 처리 |
| 컨텍스트 관리 | 채널+사용자별 대화 세션, 오래된 메시지는 요약 후 압축 |
| 에러 처리 | tool 실행 실패 시 에러 메시지를 LLM에 전달, LLM이 대안 판단 |

## 4. LLM Provider

### 4.1 인터페이스

```python
class LLMProvider(ABC):
    async def chat(self, messages, tools, model) -> LLMResponse
    async def stream(self, messages, tools, model) -> AsyncIterator[LLMChunk]

class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    usage: TokenUsage
    stop_reason: str
```

### 4.2 Provider 목록

| Provider | 방식 | 용도 | 비용 |
|----------|------|------|------|
| ClaudeAPIProvider | Anthropic API + API Key | 프로덕션 | 토큰당 과금 |
| OpenAIAPIProvider | OpenAI API + API Key | 대안 | 토큰당 과금 |
| OllamaProvider | 로컬 HTTP API | 비용 절감 | 무료 |
| CLIProvider | `claude -p` subprocess | 개인 사용, 구독 활용 | 구독료만 |
| GeminiCLIProvider | `gemini` subprocess | 개인 사용 | 구독료만 |
| CodexCLIProvider | `codex` subprocess | 개인 사용 | 구독료만 |

### 4.3 정책 준수

- CLIProvider (claude -p 등)는 개인 로컬 사용 전용으로 표시
- Agent SDK + OAuth 토큰 사용 금지 (Anthropic ToS 위반)
- 프로덕션/다수 사용자 서비스에는 API Key 사용 필수
- CLI Provider는 tool calling을 직접 지원하지 않으므로 프롬프트에 도구 스키마를 포함하고 JSON 응답을 파싱

### 4.4 모델 선택 전략

- 설정 파일(config.yaml)에서 기본 모델 지정
- 작업 유형별 모델 오버라이드 가능 (모니터링 판단 = 저비용, 복잡한 조치 = 고성능)
- fallback 체인: API Provider → CLI Provider → Ollama

## 5. Tool Manager

### 5.1 구조

```
┌─────────────────────────────────────────────┐
│                Tool Manager                  │
│                                              │
│  ┌────────────┐  ┌──────────┐  ┌──────────┐│
│  │ MCP        │  │ Built-in │  │ Custom   ││
│  │ Registry   │  │ Tools    │  │ Tools    ││
│  │ Client     │  │(fallback)│  │ (user)   ││
│  └─────┬──────┘  └────┬─────┘  └────┬─────┘│
│        └───────┬──────┘─────────────┘       │
│                ▼                             │
│       ┌────────────────┐                    │
│       │  Tool Registry │                    │
│       │  (unified)     │                    │
│       └────────┬───────┘                    │
│                ▼                             │
│       ┌────────────────┐                    │
│       │  MCP Runtime   │                    │
│       │  Manager       │                    │
│       └────────────────┘                    │
└─────────────────────────────────────────────┘
```

### 5.2 MCP 자동 탐색 + 사용자 승인 흐름

```
사용자: "Proxmox에서 VM 목록 좀 보여줘"
    │
    ▼
LLM: "proxmox 관련 도구가 없음" → mcp_search('proxmox')
    │
    ▼
MCP Registry API (registry.modelcontextprotocol.io) 검색
    │
    ▼
LLM → 사용자에게 추천:
  "MCP 서버를 찾았습니다:
   1. mcp-proxmox (gilby125)
   2. ProxmoxMCP-Plus
   설치할까요?"
    │
    ▼
사용자 승인 → mcp_install → 시작 → 도구 자동 등록
    │
    ▼
LLM → proxmox_get_vms() 호출 → 결과 반환
```

### 5.3 메타 도구

| 도구 | 역할 | 승인 필요 |
|------|------|----------|
| mcp_search | MCP Registry에서 서버 검색 | No |
| mcp_recommend | 검색 결과 추천 + 설치 여부 질문 | No |
| mcp_install | MCP 서버 설치 | **Yes (항상)** |
| mcp_uninstall | MCP 서버 제거 | **Yes (항상)** |
| mcp_list | 설치된 MCP 서버 목록 | No |
| mcp_start / mcp_stop | MCP 서버 시작/중지 | No |

### 5.4 빌트인 도구

| 도구 | 용도 |
|------|------|
| shell_exec | SSH/로컬 명령어 실행 (최후 수단) |
| web_search | 문제 해결을 위한 웹 검색 |
| file_read / file_write | 설정 파일 관리 |

## 6. Authentication

### 6.1 인증 아키텍처

웹 UI는 OAuth 2.0 / OpenID Connect 기반 SSO를 지원하고, 메신저 채널은 플랫폼 User ID 화이트리스트로 인증한다.

```
┌──────────┐     ┌──────────────────┐     ┌─────────────┐
│  Web UI  │────▶│  Auth Provider   │────▶│  Core Agent │
│          │     │  (OAuth2/OIDC)   │     │             │
└──────────┘     └──────────────────┘     └─────────────┘
                        │
              ┌─────────┼─────────┐
              ▼         ▼         ▼
         Google    Active Dir  OpenID
         OAuth2    (Entra ID)  Connect
```

### 6.2 Web UI 인증 (OAuth 2.0 / OIDC)

```yaml
# config.yaml
auth:
  web:
    providers:
      google:
        enabled: true
        client_id: "xxx.apps.googleusercontent.com"
        client_secret: "${GOOGLE_CLIENT_SECRET}"
        allowed_emails: ["user@breadpack.dev"]
      active_directory:
        enabled: false
        tenant_id: "xxx"
        client_id: "xxx"
        client_secret: "${AD_CLIENT_SECRET}"
        allowed_groups: ["InfraAdmins"]
      oidc:
        enabled: false
        issuer_url: "https://auth.example.com"
        client_id: "xxx"
        client_secret: "${OIDC_CLIENT_SECRET}"
        allowed_subjects: ["user@example.com"]
    session_ttl_hours: 24
    fallback_password_hash: "bcrypt_hash_here"  # SSO 장애 시 로컬 로그인
```

라이브러리: `authlib` (OAuth2/OIDC 클라이언트) + FastAPI 세션 미들웨어

### 6.3 메신저 인증 (플랫폼 User ID)

메신저는 각 플랫폼이 이미 사용자를 인증하므로, User ID 화이트리스트로 접근을 제어한다.

```yaml
# config.yaml
auth:
  messenger:
    slack:
      allowed_users: ["U12345678"]
    discord:
      allowed_users: ["123456789012345"]
    telegram:
      allowed_users: ["987654321"]
```

### 6.4 인증 흐름

모든 수신 메시지/요청은 Core Agent에 도달하기 전에 인증 검사를 거친다.

- **Web UI**: OAuth 토큰 검증 → 세션 확인 → 허용된 이메일/그룹 체크
- **메신저**: 플랫폼 User ID → 화이트리스트 체크
- **미인증 요청**: 무시 + 감사 로그에 기록
- **SSO 장애 시**: fallback_password_hash로 로컬 로그인 가능

## 7. Safety Guard

### 7.1 액션 분류

| 분류 | 동작 | 예시 |
|------|------|------|
| 자동 허용 | 즉시 실행 | pod 목록 조회, 로그 읽기, 상태 확인 |
| 승인 필수 (화이트리스트) | 항상 사용자 확인 | mcp_install, mcp_uninstall |
| 차단 (블랙리스트) | 실행 불가 | VM 삭제, 노드 drain, factory reset |
| 기본 | 자동 실행 | pod 재시작, 서비스 스케일 등 |

### 6.2 블랙리스트 (safety.yaml)

```yaml
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
  system:
    - shell_exec_rm_rf

require_approval:
  - mcp_install
  - mcp_uninstall
  - pve_create_vm
  - k8s_apply_manifest
  - shell_exec
```

### 6.3 감사 로그

```python
@dataclass
class AuditEntry:
    timestamp: datetime
    action: str
    params: dict
    result: str          # ALLOWED / DENIED / APPROVED / REJECTED
    reason: str
    channel: str         # slack / discord / telegram / web
    user: str
```

PostgreSQL `audit_log` 테이블에 저장, 웹 UI에서 조회 가능.

## 8. Monitoring Engine

### 7.1 수집 주기

| 대상 | 주기 | 수집 항목 |
|------|------|----------|
| K8s pods | 1분 | 상태, 재시작 횟수, 리소스 사용량 |
| K8s nodes | 5분 | CPU, 메모리, 디스크, 조건 |
| Proxmox | 5분 | VM 상태, 노드 CPU/RAM/디스크 |
| OpenWrt | 5분 | 연결 수, 인터페이스 상태, 메모리 |

### 7.2 이상 감지 흐름

```
MonitoringEngine (APScheduler)
    │ 주기적 수집
    ▼
상태 비교 (이전 스냅샷 vs 현재)
    │ 변화 감지
    ▼
규칙 기반 판단 (LLM 호출 없음)
  • pod CrashLoopBackOff → 이벤트
  • 노드 NotReady → 이벤트
  • 디스크 90% 이상 → 이벤트
  • VM stopped (예기치 않은) → 이벤트
    │
    ▼
이벤트 → Core Agent → LLM 대응 판단 → 자동 실행
    │
    ▼
결과를 메신저 채널에 알림
```

### 8.3 루프 보호

모니터링 이벤트의 무한 대응 루프를 방지한다.

```yaml
# monitoring.yaml
loop_protection:
  cooldown_minutes: 10          # 동일 대상에 같은 액션 재실행 최소 간격
  max_auto_actions: 3           # 동일 대상에 연속 자동 대응 횟수 제한
  circuit_breaker_action: notify # 제한 초과 시: notify (사람에게 에스컬레이션)
  approval_timeout_minutes: 10  # 승인 요청 타임아웃 (초과 시 deny)
```

- 동일 대상(pod, VM 등)에 동일 액션이 cooldown 내 재실행되면 억제
- max_auto_actions 초과 시 서킷브레이커 발동 → 사람에게 에스컬레이션
- 승인 요청에 10분 내 응답 없으면 자동 deny + 알림

### 8.4 규칙 설정 (monitoring.yaml)

```yaml
checks:
  k8s_pod_crash:
    condition: "restart_count_delta > 3 in 5min"
    severity: critical
  k8s_node_not_ready:
    condition: "node.condition.Ready != True"
    severity: critical
  pve_memory_high:
    condition: "memory_percent > 90"
    severity: warning
  pve_vm_unexpected_stop:
    condition: "vm.status changed from running to stopped"
    severity: critical
  owrt_wan_down:
    condition: "interface.wan.status != up"
    severity: critical

notification_channels:
  critical: [slack, discord, telegram]
  warning: [slack]
  info: [web_only]
```

## 9. Messenger Gateway

### 8.1 인터페이스

```python
class MessengerGateway(ABC):
    async def start(self)
    async def send(self, channel, message: AgentMessage)
    async def ask_approval(self, channel, action) -> bool
    def on_message(self, callback)
```

### 8.2 채널별 구현

| 채널 | 라이브러리 | 승인 UX |
|------|-----------|---------|
| Slack | slack-bolt[async] | 버튼 (승인/거절) |
| Discord | discord.py | 리액션 |
| Telegram | python-telegram-bot | 인라인 키보드 |
| Web UI | FastAPI + WebSocket | 버튼 |

### 8.3 메시지 라우팅

- 일반 메시지 → Core Agent (대화형 처리)
- 승인 응답 → Safety Guard (대기 중인 승인 해제)
- 명령어 (/status, /help) → 직접 처리 (LLM 호출 없음)

## 10. Memory System

### 9.1 3계층 하이브리드 메모리

연구 기반: A-MEM (NeurIPS 2025), Memoria (2025.12), Mem0

```
Layer 1: Working Memory (단기)
  현재 대화 컨텍스트 (최근 N턴)
  진행 중인 작업 상태
  → 세션 종료 시 요약 → Layer 2로 이동

Layer 2: Episodic Memory (에피소드 기억)
  A-MEM 방식 노트 저장:
    내용 + 키워드 + 태그 + 컨텍스트 설명
    노트 간 동적 링크 (관련 기억 연결)
    새 경험이 기존 노트를 업데이트
  벡터 임베딩으로 유사도 검색 (pgvector)

Layer 3: Semantic Memory (의미 기억)
  Knowledge Graph (Apache AGE):
    사용자 선호/습관/규칙
    인프라 엔티티 간 관계
    가중치 기반 (자주 참조 = 중요)
```

### 9.2 사용자 패턴 학습

```python
class UserProfiler:
    async def extract_preferences(self, conversation) -> list[Preference]
        # 대화에서 선호/습관/규칙 추출
    async def extract_patterns(self, action_history) -> list[Pattern]
        # 행동 패턴 분석
    async def get_user_context(self, query) -> str
        # 관련 선호/패턴을 KG에서 검색 → system prompt 주입
```

### 9.3 메모리 진화 흐름

```
새 대화/이벤트 → Working Memory
    ↓ 세션 종료/주기적
에피소드 메모리:
  LLM이 키워드/태그/컨텍스트 생성
  임베딩 → pgvector 저장
  기존 노트와 유사도 비교 → 링크 생성
  기존 노트 컨텍스트 업데이트 (A-MEM 진화)
    ↓ 패턴 감지 시
의미 메모리(KG) 업데이트:
  반복 선호 → KG 엔티티로 승격
  인프라 관계 학습 → KG 추가
  가중치 조정
```

### 9.4 컨텍스트 빌드 (LLM 호출 시)

```
System Prompt
  + 사용자 프로필 (KG에서 관련 선호/패턴)
  + 관련 에피소드 (pgvector 검색 top-5)
  + 인프라 관계 (KG에서 관련 엔티티)
  + Working Memory (현재 대화)
  + 도구 정의
```

### 9.5 기술 스택

| 컴포넌트 | 기술 |
|---------|------|
| 단기 메모리 | 인메모리 (dict) |
| 에피소드 저장 | PostgreSQL + pgvector |
| Knowledge Graph | PostgreSQL + Apache AGE |
| 임베딩 | sentence-transformers (로컬) 또는 API |
| 감사 로그 | PostgreSQL |

## 11. Project Structure

```
breadmind/
├── pyproject.toml
├── Dockerfile
├── docker-compose.yaml
├── config/
│   ├── config.yaml
│   ├── safety.yaml
│   └── monitoring.yaml
├── src/
│   └── breadmind/
│       ├── __init__.py
│       ├── main.py
│       ├── core/
│       │   ├── agent.py          # Core Agent orchestrator
│       │   ├── context.py        # Context builder
│       │   └── safety.py         # Safety Guard
│       ├── llm/
│       │   ├── base.py           # LLMProvider ABC
│       │   ├── claude.py         # Claude API
│       │   ├── openai.py         # OpenAI API
│       │   ├── ollama.py         # Ollama
│       │   └── cli.py            # CLIProvider (claude -p, gemini, codex)
│       ├── tools/
│       │   ├── registry.py       # Tool Registry (unified)
│       │   ├── mcp_client.py     # MCP Registry Client + Runtime Manager
│       │   └── builtin.py        # Built-in tools
│       ├── monitoring/
│       │   ├── engine.py         # Monitoring Engine
│       │   └── rules.py          # Rule-based anomaly detection
│       ├── messenger/
│       │   ├── router.py         # Message router
│       │   ├── slack.py
│       │   ├── discord.py
│       │   ├── telegram.py
│       │   └── web.py            # FastAPI + WebSocket
│       ├── memory/
│       │   ├── working.py        # Working Memory (in-memory)
│       │   ├── episodic.py       # Episodic Memory (pgvector)
│       │   ├── semantic.py       # Semantic Memory / KG (AGE)
│       │   └── profiler.py       # User pattern learning
│       ├── storage/
│       │   ├── database.py       # asyncpg connection, migrations
│       │   └── models.py         # DB schema
│       └── web/
│           └── static/           # Web UI frontend
├── k8s/
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── configmap.yaml
│   └── postgres-statefulset.yaml
└── tests/
```

## 12. Deployment

### Docker Compose (개발/독립 배포)

```yaml
services:
  breadmind:
    build: .
    env_file: .env
    depends_on: [postgres]
    ports: ["8080:8080"]
  postgres:
    build: ./docker/postgres    # Custom image: PostgreSQL + pgvector + AGE
    volumes: ["pgdata:/var/lib/postgresql/data"]
    environment:
      POSTGRES_DB: breadmind
      POSTGRES_PASSWORD: ${DB_PASSWORD}
```

### K8s (프로덕션)

- Deployment: breadmind (1 replica)
- StatefulSet: PostgreSQL with AGE + pgvector
- ConfigMap: config.yaml, safety.yaml, monitoring.yaml
- Secret: API keys, bot tokens, DB password

## 13. Error Handling & Self-Monitoring

### 12.1 에러 처리

| 상황 | 대응 |
|------|------|
| Tool 실행 타임아웃 | 30초 기본, 설정 가능. 초과 시 에러를 LLM에 전달 |
| Tool 실행 실패 | 에러 메시지를 LLM에 전달, LLM이 대안 판단 (재시도 없음) |
| LLM Provider 장애 | fallback 체인 순회. 전부 실패 시 이벤트 큐에 보관 + 비-LLM 경로로 알림 |
| DB 연결 실패 | 재연결 시도 (exponential backoff), 실패 지속 시 메신저로 알림 |
| MCP 서버 크래시 | 자동 재시작 (최대 3회), 초과 시 비활성화 + 알림 |

### 12.2 자기 모니터링

에이전트 자체의 건강 상태를 주기적으로 (1분) 확인한다.

- DB 연결 상태 (PostgreSQL)
- 메신저 연결 상태 (Slack/Discord/Telegram)
- LLM Provider 가용성
- 실행 중인 MCP 서버 상태
- 메모리 사용량, 디스크 사용량

`/health` 엔드포인트로 외부에서도 확인 가능 (K8s liveness/readiness probe 연동).

### 12.3 데이터 보존 정책

| 데이터 | 보존 기간 |
|--------|----------|
| 감사 로그 | 90일 |
| 에피소드 메모리 | 무제한 (관련도 낮은 항목 주기적 정리) |
| Knowledge Graph | 무제한 |
| 인프라 스냅샷 | 30일 |
| Working Memory | 세션 종료 시 요약 후 삭제 |

## 14. Sub-projects (향후)

| # | 서브프로젝트 | 설명 |
|---|-------------|------|
| 1 | **Core Agent** (이 문서) | 오케스트레이터, LLM, Safety, Memory |
| 2 | **Infrastructure Adapters** | K8s/Proxmox/OpenWrt MCP 활용 |
| 3 | **Monitoring Engine** | 상태 수집, 규칙 엔진, 자동 대응 |
| 4 | **Messenger Gateway** | Slack/Discord/Telegram/Web 통합 |
| 5 | **Web Dashboard** | 상태 조회, 로그, 설정 관리 UI |

각 서브프로젝트는 독립된 스펙 → 플랜 → 구현 사이클로 진행.

## 15. Tech Stack Summary

| 영역 | 기술 |
|------|------|
| Language | Python 3.12+ |
| Web Framework | FastAPI |
| Async | asyncio, asyncpg |
| Database | PostgreSQL + pgvector + Apache AGE |
| Scheduler | APScheduler |
| Messenger | slack-bolt, discord.py, python-telegram-bot |
| Embedding | sentence-transformers |
| LLM | anthropic, openai, ollama, subprocess (CLI) |
| MCP | MCP Registry API (registry.modelcontextprotocol.io) |
| Container | Docker, K8s |

## 16. References

- [A-MEM: Agentic Memory for LLM Agents (NeurIPS 2025)](https://arxiv.org/abs/2502.12110)
- [Memoria: Scalable Agentic Memory Framework](https://arxiv.org/abs/2512.12686)
- [Mem0 - Graph Memory for AI Agents](https://mem0.ai/blog/graph-memory-solutions-ai-agents)
- [Episodic Memory is the Missing Piece for Long-Term LLM Agents](https://arxiv.org/pdf/2502.06975)
- [MCP Registry API](https://registry.modelcontextprotocol.io/)
- [Claude Code Headless Mode](https://code.claude.com/docs/en/headless)
- [Claude Code Legal & Compliance](https://code.claude.com/docs/en/legal-and-compliance)
