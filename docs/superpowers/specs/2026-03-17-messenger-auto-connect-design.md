# Messenger Auto-Connect System Design

## Summary

BreadMind의 메신저 연결(Slack, Discord, Telegram, WhatsApp, Gmail, Signal) 과정을 최대한 자동화하고, 웹 UI / 채팅 / CLI 세 인터페이스에서 통합된 경험을 제공한다. 결정적(deterministic) 흐름은 AutoConnector가, 예외 상황은 에이전트가 처리하는 하이브리드 방식.

## Architecture

```
┌──────────────────────────────────────────────┐
│              User Interfaces                  │
│  Web UI Wizard  │  Chat Command  │  CLI Setup │
└───────┬─────────┴───────┬───────┴─────┬──────┘
        │                 │             │
        ▼                 ▼             ▼
┌──────────────────────────────────────────────┐
│           ConnectionOrchestrator              │
│  - 위자드 상태 머신 (step tracking)            │
│  - 플랫폼 감지 & AutoConnector 선택            │
│  - 에이전트 판단 위임 (예외/질문 시)            │
└──────────────────┬───────────────────────────┘
                   │
   ┌───────┬───────┼───────┬───────┬───────┐
   ▼       ▼       ▼       ▼       ▼       ▼
 Telegram Slack  Discord WhatsApp Gmail  Signal
  Auto    Auto    Auto    Auto    Auto    Auto
 Connect. Connect. Conn.  Connect. Conn.  Conn.
                   │
                   ▼
┌──────────────────────────────────────────────┐
│         GatewayLifecycleManager               │
│  - 부트스트랩 시 자동 시작                      │
│  - 지수 백오프 재시도                           │
│  - 상태 모니터링 & 이벤트 발행                   │
└──────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│            SecurityManager                    │
│  - 토큰 암호화 저장                            │
│  - UI 토큰 마스킹                             │
│  - 접근 로그 기록                              │
│  - 토큰 만료/로테이션 알림                      │
└──────────────────────────────────────────────┘
```

## Components

### 1. AutoConnector (Base Class)

`src/breadmind/messenger/auto_connect/base.py`

```python
class AutoConnector(ABC):
    platform: str

    async def get_setup_steps(self) -> list[SetupStep]
    async def create_bot(self, params: dict) -> CreateResult
    async def validate_credentials(self, credentials: dict) -> ValidationResult
    async def connect(self, credentials: dict) -> ConnectionResult
    async def health_check(self) -> HealthStatus
    async def get_invite_url(self, credentials: dict) -> str | None
```

`SetupStep` dataclass:
```python
@dataclass
class SetupStep:
    step_number: int
    title: str
    description: str
    action_type: str  # "auto" | "user_input" | "user_action" | "oauth_redirect"
    action_url: str | None  # 외부 링크 (BotFather, Developer Portal 등)
    input_fields: list[InputField] | None  # 사용자 입력 필요 시
    auto_executable: bool  # 자동 실행 가능 여부
```

### 2. Platform-Specific AutoConnectors

#### Telegram (`auto_connect/telegram.py`)
- 자동화 수준: 90%
- `get_setup_steps()`: BotFather 딥링크 제공 → 토큰 입력 → 자동 검증
- `validate_credentials()`: `getMe()` API 호출로 봇 정보 확인
- 수동 단계: BotFather에서 토큰 복사 1회

#### Slack (`auto_connect/slack.py`)
- 자동화 수준: 95%
- `create_bot()`: App Manifest API로 앱 자동 생성 (workspace admin 토큰 필요 시 OAuth flow)
- `get_setup_steps()`: OAuth 설치 URL 생성 → 사용자 "허용" 클릭
- OAuth 콜백으로 bot_token, app_token 자동 획득
- 수동 단계: "허용" 클릭 1회

#### Discord (`auto_connect/discord.py`)
- 자동화 수준: 60%
- `get_setup_steps()`: Developer Portal 가이드 → 토큰 입력 → 초대 URL 자동 생성
- `get_invite_url()`: OAuth2 URL 생성 (bot + applications.commands 권한)
- `validate_credentials()`: 봇 info 조회
- 수동 단계: 봇 생성 + 토큰 복사 + 서버 초대

#### WhatsApp (`auto_connect/whatsapp.py`)
- 자동화 수준: 70%
- `get_setup_steps()`: Twilio 계정 정보 입력 안내
- `connect()`: Twilio API 검증 + 웹훅 URL 자동 등록
- 수동 단계: Twilio SID/Token 복사

#### Gmail (`auto_connect/gmail.py`)
- 자동화 수준: 80%
- `get_setup_steps()`: Google Cloud 프로젝트 설정 가이드 OR OAuth flow
- OAuth 콜백으로 refresh_token 자동 획득
- 수동 단계: Google Cloud 설정 + OAuth 허용

#### Signal (`auto_connect/signal.py`)
- 자동화 수준: 75%
- `get_setup_steps()`: signal-cli 설치 감지 → 미설치 시 설치 스크립트
- `create_bot()`: signal-cli register + verify 자동 실행
- 수동 단계: 전화번호 입력 + SMS 인증

### 3. ConnectionOrchestrator

`src/breadmind/messenger/auto_connect/orchestrator.py`

위자드 상태 머신으로 3개 인터페이스(웹/채팅/CLI)의 연결 요청을 통합 처리.

```python
class ConnectionOrchestrator:
    async def start_connection(self, platform: str, interface: str) -> WizardState
    async def process_step(self, session_id: str, user_input: dict) -> WizardState
    async def get_current_state(self, session_id: str) -> WizardState
    async def cancel(self, session_id: str) -> None
```

`WizardState`:
```python
@dataclass
class WizardState:
    session_id: str
    platform: str
    current_step: int
    total_steps: int
    step_info: SetupStep
    status: str  # "waiting_input" | "processing" | "completed" | "failed"
    message: str  # 사용자에게 보여줄 메시지
    error: str | None
```

에이전트 위임 조건:
- 사용자가 자연어 질문을 할 때 ("이 토큰이 뭐예요?")
- 예외 상황 발생 시 (토큰 거부, 권한 부족 등)
- 복합 요청 시 ("슬랙이랑 디스코드 둘 다 연결해줘")

### 4. GatewayLifecycleManager

`src/breadmind/messenger/lifecycle.py`

```python
class GatewayLifecycleManager:
    async def auto_start_all(self) -> dict[str, bool]
    async def start_gateway(self, platform: str) -> bool
    async def stop_gateway(self, platform: str) -> bool
    async def health_check_all(self) -> dict[str, HealthStatus]
    async def get_status(self, platform: str) -> GatewayStatus
```

상태 모델:
```
UNCONFIGURED → CONFIGURED → CONNECTING → CONNECTED
                                  ↓
                            DISCONNECTED → RECONNECTING → CONNECTED
                                  ↓
                             FAILED (max retry 초과)
```

재시도 정책:
- 지수 백오프: 1s → 2s → 4s → 8s → ... → max 5분
- 최대 재시도: 10회
- 실패 시: 이벤트 발행 + 연결된 다른 메신저로 알림

부트스트랩 통합:
- `bootstrap.py`에서 `GatewayLifecycleManager.auto_start_all()` 호출
- DB에서 `messenger_auto_start:{platform}` 설정 조회 (기본값: True)
- 30초 간격 health_check 루프

### 5. SecurityManager

`src/breadmind/messenger/security.py`

```python
class MessengerSecurityManager:
    async def store_token(self, platform: str, key: str, value: str) -> None
    async def get_token(self, platform: str, key: str) -> str | None
    async def mask_token(self, token: str) -> str  # "xoxb-****-****-abcd"
    async def log_access(self, platform: str, action: str, user: str) -> None
    async def check_token_expiry(self, platform: str) -> ExpiryStatus
    async def get_access_logs(self, platform: str, limit: int) -> list[AccessLog]
```

기능:
- 토큰 마스킹: UI에서 토큰 표시 시 중간 부분 마스킹
- 접근 로그: 토큰 조회/수정/삭제 시 기록 (who, when, what)
- 만료 감지: OAuth 토큰(Slack, Gmail) 만료 시점 추적 + 사전 알림
- 로테이션 알림: 토큰 나이가 설정 기간 초과 시 교체 권장 알림

### 6. API Endpoints (추가/수정)

```
# 기존 유지
GET  /api/messenger/platforms
POST /api/messenger/{platform}/token
POST /api/messenger/{platform}/test
GET  /api/messenger/{platform}/setup-url
GET  /api/messenger/slack/oauth-callback
GET  /api/messenger/gmail/oauth-callback

# 신규
POST /api/messenger/{platform}/auto-connect      → 자동 연결 위자드 시작
POST /api/messenger/wizard/{session_id}/step      → 위자드 다음 단계 진행
GET  /api/messenger/wizard/{session_id}/status     → 위자드 현재 상태
DELETE /api/messenger/wizard/{session_id}          → 위자드 취소

GET  /api/messenger/lifecycle/status              → 전체 게이트웨이 상태
POST /api/messenger/lifecycle/{platform}/restart   → 게이트웨이 재시작
GET  /api/messenger/lifecycle/health               → 전체 health check

GET  /api/messenger/security/logs                  → 접근 로그 조회
GET  /api/messenger/security/{platform}/expiry     → 토큰 만료 상태
```

### 7. Chat & CLI Interface

#### Chat (에이전트 빌트인 도구)
기존 `messenger_connect` 도구를 확장:
```python
# "슬랙 연결해줘" → orchestrator.start_connection("slack", "chat")
# 위자드 상태에 따라 에이전트가 사용자에게 안내/질문
# 에이전트가 자동 실행 가능한 단계는 직접 실행
```

#### CLI
```bash
breadmind setup messenger              # 대화형 플랫폼 선택 + 위자드
breadmind setup messenger --platform slack  # 특정 플랫폼 직접 연결
breadmind messenger status              # 전체 상태 확인
breadmind messenger restart <platform>  # 재시작
```

### 8. File Structure

```
src/breadmind/messenger/
├── auto_connect/
│   ├── __init__.py
│   ├── base.py              # AutoConnector ABC, SetupStep, dataclasses
│   ├── orchestrator.py      # ConnectionOrchestrator (위자드 상태 머신)
│   ├── telegram.py          # TelegramAutoConnector
│   ├── slack.py             # SlackAutoConnector
│   ├── discord.py           # DiscordAutoConnector
│   ├── whatsapp.py          # WhatsAppAutoConnector
│   ├── gmail.py             # GmailAutoConnector
│   └── signal.py            # SignalAutoConnector
├── lifecycle.py             # GatewayLifecycleManager
├── security.py              # MessengerSecurityManager
├── router.py                # (기존) MessageRouter 수정 — lifecycle 통합
├── slack.py                 # (기존) SlackGateway
├── discord_gw.py            # (기존)
├── telegram_gw.py           # (기존)
├── whatsapp_gw.py           # (기존)
├── gmail_gw.py              # (기존)
└── signal_gw.py             # (기존)
```

## Implementation Notes (from spec review)

### Bootstrap Integration
- `bootstrap.py`에 `init_messenger()` 함수 추가 — `init_tools()`, `init_memory()` 패턴과 동일
- `init_messenger()`에서 `MessageRouter` 생성 → `GatewayLifecycleManager` 초기화 → `auto_start_all()` 호출
- `MessageRouter`를 `AppState`에 저장하여 WebApp에 전달

### OAuth Callback Coordination
- 기존 `system.py`의 Slack/Gmail OAuth 콜백을 `ConnectionOrchestrator`로 위임하도록 리팩토링
- 콜백에서 `orchestrator.process_step()` 호출하여 위자드 상태 자동 전진
- 기존 API 엔드포인트 URL은 유지 (하위 호환성)

### Wizard Session Management
- 인메모리 딕셔너리로 위자드 세션 관리 (재시작 시 소멸 — 연결 설정은 일시적 과정)
- 세션 TTL: 30분 (미완료 시 자동 정리)
- 같은 플랫폼에 대한 중복 세션 방지: 기존 세션 있으면 이어서 진행

### Retry Policy Details
- 백오프 캡: `min(2^attempt, 300)` 초
- 10회 실패 후 FAILED 상태 전환, 이벤트 발행
- FAILED 상태에서도 수동 재시작 가능

### Health Check Loop
- `asyncio.create_task()`로 백그라운드 태스크 생성
- `app.on_event("shutdown")`에서 태스크 취소
- health_check 실패 시 자동 reconnect 트리거

### Token Security
- `SecurityManager`는 기존 `db.set_setting()` 래핑 — 추가로 접근 로그 기록
- 마스킹 규칙: 처음 4자 + "****" + 마지막 4자 (8자 미만이면 전체 마스킹)
- 로그에는 마스킹된 토큰만 기록

### CLI Integration
- `src/breadmind/cli/messenger.py`에 CLI 명령 구현
- 기존 `cli/main.py`의 서브커맨드로 등록
- CLI는 `ConnectionOrchestrator`를 직접 호출 (웹 서버 불필요)

## Testing Strategy

- 각 AutoConnector: 모의(mock) API 응답으로 단위 테스트
- ConnectionOrchestrator: 상태 전이 테스트
- GatewayLifecycleManager: 재시도 로직 + 상태 전이 테스트
- SecurityManager: 마스킹/로그/만료 감지 테스트
- 통합 테스트: 실제 토큰 없이 전체 위자드 흐름 테스트

## Success Criteria

1. 모든 플랫폼에서 수동 단계가 최소화됨
2. 웹/채팅/CLI 세 인터페이스에서 동일한 연결 경험 제공
3. 부트스트랩 시 설정된 게이트웨이 자동 시작
4. 연결 끊김 시 자동 재연결
5. 토큰 보안 강화 (마스킹, 접근 로그, 만료 알림)
