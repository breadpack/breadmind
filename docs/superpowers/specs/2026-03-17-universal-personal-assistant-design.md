# BreadMind Universal Personal Assistant — Design Spec

**Date**: 2026-03-17
**Goal**: BreadMind를 범용 개인 비서로 확장하여 OpenClaw 대비 체감 품질 우위 확보
**Strategy**: 하이브리드 — 통합 아키텍처 + 수직 시나리오 검증 → 확장
**Success Criteria**: 같은 기능이라도 BreadMind가 더 잘한다 (크로스 도메인 연결, 맥락 기억, 능동적 제안)

## 1. Universal Domain Model

모든 범용 기능이 공유하는 5개 핵심 도메인 엔티티.

### 1.1 Task

```python
@dataclass
class Task:
    id: str
    title: str
    description: str | None = None
    status: Literal["pending", "in_progress", "done", "cancelled"] = "pending"
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    due_at: datetime | None = None
    recurrence: str | None = None          # "daily", "weekly", cron expression
    tags: list[str] = field(default_factory=list)
    source: str = "builtin"                # "builtin" | "google_tasks" | "notion" | "jira" | "github"
    source_id: str | None = None           # 외부 서비스 원본 ID
    assignee: str | None = None
    parent_id: str | None = None           # 하위 작업 지원
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

### 1.2 Event

```python
@dataclass
class Event:
    id: str
    title: str
    description: str | None = None
    start_at: datetime
    end_at: datetime
    all_day: bool = False
    location: str | None = None
    attendees: list[str] = field(default_factory=list)
    reminder_minutes: list[int] = field(default_factory=lambda: [15])
    recurrence: str | None = None           # RFC 5545 RRULE 형식 (예: "FREQ=WEEKLY;BYDAY=MO,WE")
    source: str = "builtin"                # "builtin" | "google_calendar" | "outlook"
    source_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

### 1.3 Contact

```python
@dataclass
class Contact:
    id: str
    name: str
    email: str | None = None
    phone: str | None = None
    platform_ids: dict[str, str] = field(default_factory=dict)  # {"telegram": "123", "slack": "U456"}
    organization: str | None = None
    tags: list[str] = field(default_factory=list)
    notes: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

### 1.4 File

```python
@dataclass
class File:
    id: str
    name: str
    path_or_url: str
    mime_type: str
    size_bytes: int = 0
    source: str = "local"                  # "local" | "google_drive" | "onedrive" | "dropbox"
    source_id: str | None = None
    parent_folder: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

### 1.5 Message (검색/요약용, Phase 4에서 어댑터 구현)

```python
@dataclass
class Message:
    id: str
    content: str
    sender: str
    channel: str
    platform: str
    thread_id: str | None = None
    attachments: list[str] = field(default_factory=list)  # File ID 목록
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

### 1.6 Recurrence 표준

모든 recurrence 필드는 RFC 5545 RRULE 형식을 사용:
- 단축어 지원: `"daily"` → `"FREQ=DAILY"`, `"weekly"` → `"FREQ=WEEKLY"`
- 전체 RRULE: `"FREQ=WEEKLY;BYDAY=MO,WE,FR"`, `"FREQ=MONTHLY;BYMONTHDAY=15"`
- 파싱: `python-dateutil` 라이브러리의 `rrulestr()` 사용

### 1.7 도메인 모델 원칙

- **Source-agnostic**: 모든 엔티티는 `source` + `source_id`로 외부 서비스와 양방향 동기화
- **3계층 메모리 연결**: Task 완료 → Episodic Memory 기록, Contact → Semantic Memory KGEntity 승격
- **크로스 도메인 쿼리**: "내일 회의 전에 끝내야 할 일" → Event + Task 조인 가능

## 2. Service Adapter Layer

### 2.1 통합 인터페이스

```python
class ServiceAdapter(ABC):
    """모든 외부 서비스가 구현하는 통합 인터페이스"""

    @property
    @abstractmethod
    def domain(self) -> str:
        """도메인: "task", "event", "contact", "file", "message" """

    @property
    @abstractmethod
    def source(self) -> str:
        """소스: "google_calendar", "notion", "builtin" 등"""

    @abstractmethod
    async def authenticate(self, credentials: dict) -> bool: ...

    @abstractmethod
    async def list_items(self, filters: dict | None = None, limit: int = 50) -> list: ...

    @abstractmethod
    async def get_item(self, source_id: str) -> Any: ...

    @abstractmethod
    async def create_item(self, entity: Any) -> str: ...

    @abstractmethod
    async def update_item(self, source_id: str, changes: dict) -> bool: ...

    @abstractmethod
    async def delete_item(self, source_id: str) -> bool: ...

    @abstractmethod
    async def sync(self, since: datetime | None = None) -> "SyncResult": ...
```

### 2.2 SyncResult

```python
@dataclass
class SyncResult:
    created: list[str]    # 새로 생성된 엔티티 ID
    updated: list[str]    # 업데이트된 엔티티 ID
    deleted: list[str]    # 삭제된 엔티티 ID
    errors: list[str]     # 동기화 실패 항목
    synced_at: datetime
```

### 2.3 AdapterRegistry

```python
class AdapterRegistry:
    """어댑터 자동 등록 및 조회. MCP ToolRegistry와 동일한 패턴."""

    def register(self, adapter: ServiceAdapter) -> None:
        """domain + source 키로 어댑터 등록"""

    def get_adapter(self, domain: str, source: str) -> ServiceAdapter:
        """특정 도메인-소스 어댑터 조회"""

    def list_adapters(self, domain: str | None = None) -> list[ServiceAdapter]:
        """도메인별 또는 전체 어댑터 목록"""

    async def sync_all(self, domain: str | None = None) -> dict[str, SyncResult]:
        """모든 어댑터 동기화 실행"""
```

### 2.4 어댑터 구현 계획

| Phase | 어댑터 | 도메인 |
|-------|--------|--------|
| 2 | BuiltinTaskAdapter | task |
| 2 | BuiltinEventAdapter | event |
| 2 | GoogleCalendarAdapter | event |
| 3 | GoogleDriveAdapter | file |
| 3 | GoogleContactsAdapter | contact |
| 3 | NotionAdapter | task, file |
| 3 | JiraAdapter | task |
| 3 | GitHubIssuesAdapter | task |
| 4 | OutlookCalendarAdapter | event |
| 4 | OneDriveAdapter | file |

## 3. Intent Classification 확장

### 3.1 새로운 의도 카테고리 (4개 추가)

기존 6개 카테고리(QUERY, EXECUTE, DIAGNOSE, CONFIGURE, LEARN, CHAT)에 추가:

| 카테고리 | 패턴 키워드 | 도구 힌트 |
|---------|-----------|---------|
| **SCHEDULE** | 일정, 회의, 약속, 캘린더, 언제, 시간, 예약 | event_create, event_list, event_update |
| **TASK** | 할 일, 해야 할, 완료, 체크, 리마인더, 마감 | task_create, task_list, task_update |
| **SEARCH_FILES** | 파일, 문서, 찾아, 드라이브, 공유, 다운로드 | file_search, file_read, file_list |
| **CONTACT** | 연락처, 전화번호, 이메일 주소, 누구, 담당자 | contact_search, contact_create |

### 3.2 구현 방식

기존 `intent.py`의 패턴 매칭 방식을 유지하면서 새 카테고리 추가.
IntentCategory enum 확장 + INTENT_PATTERNS dict에 새 패턴 등록.

### 3.3 의도 우선순위 규칙

새 카테고리(SCHEDULE, TASK 등)와 기존 EXECUTE가 동시 매칭될 때의 해결 규칙:

1. **도메인 키워드 우선**: "할 일 생성해줘" → "할 일"이 TASK 신호이므로 TASK 우선
2. **순서**: SCHEDULE > TASK > CONTACT > SEARCH_FILES > EXECUTE > QUERY > CHAT
3. **근거**: 도메인 특화 카테고리가 범용 카테고리(EXECUTE)보다 더 구체적인 도구 힌트를 제공

## 4. Adaptive User Profile

기존 `memory/profiler.py`의 `UserProfiler`를 확장하여 역할 관리를 추가한다.
새로운 UserProfile 클래스를 만들지 않고, 기존 UserProfiler에 필드를 추가하는 방식.

### 4.1 UserProfiler 확장

```python
# memory/profiler.py 기존 클래스에 추가할 필드/메서드
class UserProfiler:
    # ... 기존 코드 유지 ...

    # 추가 필드 (DB 저장)
    role: Literal["developer", "general", "auto"] = "auto"
    exposed_domains: list[str] = ["tasks", "calendar", "contacts", "files", "chat"]
    intent_history: dict[str, int] = {}  # 카테고리별 사용 횟수

    async def determine_role(self, user_id: str) -> str:
        """첫 10회 대화의 의도 패턴을 분석하여 역할 자동 결정"""
        ...

    def get_exposed_tools(self, role: str) -> set[str]:
        """역할에 따라 노출할 도구 집합 반환"""
        ...
```

### 4.2 자동 역할 결정 (auto 모드)

```
첫 10회 대화에서 의도 패턴 분석:
- EXECUTE/DIAGNOSE/CONFIGURE 비율 > 40% → developer
- SCHEDULE/TASK/CHAT 비율 > 60% → general
- 그 외 → developer (기본, 더 많은 기능 노출)
```

### 4.3 역할별 도구 노출

- **developer**: 모든 도구 (인프라 + 개인 비서)
- **general**: 인프라 도구 숨김 (shell_exec, k8s_*, proxmox_* 등), 개인 비서 도구만 노출
- 사용자가 명시적으로 역할 전환 가능: "인프라 모드로 전환해줘"

## 5. Conversation Quality Enhancement

### 5.1 크로스 도메인 컨텍스트

ContextBuilder에 "context provider" 플러그인 패턴을 도입하여, 도메인 컨텍스트를 외부에서 주입.
기존 skill_store가 주입되는 방식과 동일한 패턴 사용.

```python
# ContextProvider 인터페이스 (새로 추가)
class ContextProvider(ABC):
    @abstractmethod
    async def get_context(self, session_id: str, message: str, intent: IntentResult) -> list[LLMMessage]:
        """의도에 따라 관련 컨텍스트를 반환"""

# 도메인 컨텍스트 프로바이더 (personal/context_provider.py)
class PersonalContextProvider(ContextProvider):
    def __init__(self, adapter_registry: AdapterRegistry):
        self._registry = adapter_registry

    async def get_context(self, session_id, message, intent):
        if intent.category not in ("SCHEDULE", "TASK"):
            return []

        upcoming_events = await self._registry.get_adapter("event", "builtin").list_items(
            {"start_after": now, "start_before": now + timedelta(days=2)}
        )
        pending_tasks = await self._registry.get_adapter("task", "builtin").list_items(
            {"status": "pending", "due_before": now + timedelta(days=2)}
        )
        return [LLMMessage(
            role="system",
            content=f"## Upcoming Context\n- Events: {upcoming_events}\n- Due Tasks: {pending_tasks}"
        )]

# ContextBuilder에 등록 (DI를 통해)
context_builder.register_provider(PersonalContextProvider(adapter_registry))
```

### 5.2 능동적 제안 (Proactive Suggestions)

기존 MonitoringEngine과는 패러다임이 다르므로(인프라 상태 비교 vs 시간 기반 리마인더),
별도의 `PersonalScheduler`를 구현한다.

```python
# personal/proactive.py
class PersonalScheduler:
    """개인 비서용 스케줄러. 리마인더, 마감 경고, 패턴 감지를 담당."""

    def __init__(self, adapter_registry: AdapterRegistry, messenger_router: MessageRouter):
        self._registry = adapter_registry
        self._router = messenger_router
        self._check_interval = 60  # 1분마다 체크

    async def start(self):
        """백그라운드 루프 시작"""
        while True:
            await self._check_reminders()
            await self._check_deadlines()
            await asyncio.sleep(self._check_interval)

    async def _check_reminders(self):
        """Event.reminder_minutes에 해당하는 시간이 되면 메신저로 알림"""
        events = await self._registry.get_adapter("event", "builtin").list_items(
            {"start_after": now, "start_before": now + timedelta(hours=2)}
        )
        for event in events:
            for minutes in event.reminder_minutes:
                if (event.start_at - now).total_seconds() / 60 <= minutes:
                    await self._notify(f"📅 {minutes}분 후: {event.title}")

    async def _check_deadlines(self):
        """마감 임박 Task 경고 (24시간 이내)"""
        tasks = await self._registry.get_adapter("task", "builtin").list_items(
            {"status": "pending", "due_before": now + timedelta(hours=24)}
        )
        for task in tasks:
            if not task._deadline_notified:  # 중복 알림 방지
                await self._notify(f"⚠️ 마감 임박: {task.title} ({task.due_at})")

    async def _notify(self, message: str):
        """활성 메신저 채널로 알림 전송"""
        await self._router.broadcast_notification(message)
```

### 5.2.1 reminder_set 도구의 저장

`reminder_set` 도구는 별도 테이블 없이 Event로 저장한다:
- `reminder_set(message="약 먹기", remind_at="18:00", recurrence="daily")`
- → Event 생성: `title=message, start_at=remind_at, end_at=remind_at, reminder_minutes=[0]`
- 이렇게 하면 Event와 리마인더가 같은 파이프라인으로 처리됨

### 5.3 감정/톤 인식

의도 분류 시 긴급도 점수 추가:

```python
@dataclass
class IntentResult:
    category: str
    confidence: float
    entities: list[str]
    tool_hints: set[str]
    urgency: Literal["low", "normal", "high", "critical"] = "normal"
    # "지금 당장", "급해", "ASAP" → critical
    # "시간 될 때", "천천히" → low
```

urgency에 따라 시스템 프롬프트에서 응답 스타일 조절:
- critical → 간결하고 즉각 행동
- low → 상세한 설명 + 선택지 제공

## 6. Messenger Expansion

### 6.1 우선 추가 대상 (Phase 4)

| 플랫폼 | API 방식 | 자동화 수준 |
|--------|---------|----------|
| **Microsoft Teams** | Graph API + Bot Framework | 80% (앱 등록 1회) |
| **LINE** | Messaging API | 85% (채널 토큰 1회) |
| **Matrix** | matrix-nio (E2E 암호화) | 90% (홈서버 + 토큰) |
| **iMessage** | AppleScript/Shortcuts (macOS only) | 60% (OS 제한) |

### 6.2 게이트웨이 구현 패턴

기존 `messenger/` 패턴을 그대로 따름:
- `MessengerGateway` ABC 상속 (messenger/router.py)
- `auto_connect/` 커넥터 추가
- `lifecycle.py`에 헬스체크 등록

## 7. Sync & Auth

### 7.1 동기화 충돌 해결 (Conflict Resolution)

양방향 동기화 시 충돌 해결 전략:

| 상황 | 전략 | 근거 |
|------|------|------|
| 로컬만 수정됨 | 로컬 → 외부 push | 단방향, 충돌 없음 |
| 외부만 수정됨 | 외부 → 로컬 pull | 단방향, 충돌 없음 |
| 양쪽 동시 수정 | **Last-writer-wins** (updated_at 비교) | 단순하고 예측 가능. 개인 비서 특성상 한 사용자가 양쪽을 동시에 수정하는 경우가 드묾 |
| 네트워크 단절 | 로컬 변경을 큐에 저장, 복구 시 순서대로 push | 오프라인 우선 지원 |

충돌 발생 시 감사 로그에 기록하고, 덮어쓰인 버전은 `sync_conflicts` 테이블에 30일 보관.

### 7.2 OAuth 인증 관리

기존 Gmail 게이트웨이(`gmail_gw.py`)의 Google OAuth를 공통 OAuth 매니저로 통합:

```python
# personal/oauth.py
class OAuthManager:
    """Google, Microsoft 등의 OAuth 2.0 credential을 중앙 관리"""

    async def get_credentials(self, provider: str, user_id: str) -> Credentials:
        """저장된 credential 반환. 만료 시 자동 refresh."""

    async def start_auth_flow(self, provider: str, scopes: list[str]) -> str:
        """OAuth 인증 URL 반환. 웹 UI 또는 CLI에서 redirect 처리."""

    async def handle_callback(self, provider: str, code: str, user_id: str) -> bool:
        """OAuth callback 처리. credential 저장."""
```

- Google 서비스(Calendar, Drive, Contacts, Gmail)는 같은 credential을 공유, scope만 추가
- credential은 기존 `config_store`의 암호화 저장소에 보관
- token refresh는 자동 (google-auth 라이브러리 활용)

## 8. Storage 확장

### 7.1 새 테이블

```sql
-- UUID 확장 (PostgreSQL 14 미만에서 필요)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 도메인 엔티티 테이블
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    description TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    priority VARCHAR(10) DEFAULT 'medium',
    due_at TIMESTAMPTZ,
    recurrence TEXT,
    tags TEXT[] DEFAULT '{}',
    source VARCHAR(50) DEFAULT 'builtin',
    source_id TEXT,
    assignee TEXT,
    parent_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    user_id TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    description TEXT,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    all_day BOOLEAN DEFAULT FALSE,
    location TEXT,
    attendees TEXT[] DEFAULT '{}',
    reminder_minutes INT[] DEFAULT '{15}',
    recurrence TEXT,
    source VARCHAR(50) DEFAULT 'builtin',
    source_id TEXT,
    user_id TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    platform_ids JSONB DEFAULT '{}',
    organization TEXT,
    tags TEXT[] DEFAULT '{}',
    notes TEXT,
    user_id TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    path_or_url TEXT NOT NULL,
    mime_type TEXT,
    size_bytes BIGINT DEFAULT 0,
    source VARCHAR(50) DEFAULT 'local',
    source_id TEXT,
    parent_folder TEXT,
    user_id TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 동기화 상태 추적
CREATE TABLE sync_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    adapter_domain VARCHAR(50) NOT NULL,
    adapter_source VARCHAR(50) NOT NULL,
    user_id TEXT NOT NULL,
    last_synced_at TIMESTAMPTZ,
    sync_token TEXT,  -- 외부 서비스의 incremental sync token
    UNIQUE(adapter_domain, adapter_source, user_id)
);

-- 동기화 충돌 보관 (30일 TTL)
CREATE TABLE sync_conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_table VARCHAR(50) NOT NULL,
    entity_id UUID NOT NULL,
    local_data JSONB NOT NULL,
    remote_data JSONB NOT NULL,
    resolution VARCHAR(20) NOT NULL,  -- 'local_wins' | 'remote_wins'
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 7.2 인덱스

```sql
CREATE INDEX idx_tasks_user_status ON tasks(user_id, status);
CREATE INDEX idx_tasks_due_at ON tasks(due_at) WHERE status = 'pending';
CREATE INDEX idx_events_user_time ON events(user_id, start_at);
CREATE INDEX idx_contacts_user ON contacts(user_id);
CREATE INDEX idx_files_user_source ON files(user_id, source);
```

## 8. 새 도구 (LLM Tool Definitions)

Phase 2에서 추가할 LLM 도구:

| 도구 | 설명 | 인자 |
|------|------|------|
| `task_create` | 할 일 생성 | title, description?, due_at?, priority?, tags? |
| `task_list` | 할 일 목록 조회 | status?, priority?, due_before?, tags? |
| `task_update` | 할 일 상태/내용 수정 | task_id, status?, title?, due_at?, priority? |
| `task_delete` | 할 일 삭제 | task_id |
| `event_create` | 일정 생성 | title, start_at, end_at?, all_day?, location?, attendees?, reminder_minutes? |
| `event_list` | 일정 목록 조회 | start_after?, start_before?, attendees? |
| `event_update` | 일정 수정 | event_id, title?, start_at?, end_at?, location? |
| `event_delete` | 일정 삭제 | event_id |
| `reminder_set` | 리마인더 설정 | message, remind_at, recurrence? |
| `contact_search` | 연락처 검색 | query (이름, 이메일, 조직 등) |
| `contact_create` | 연락처 추가 | name, email?, phone?, organization? |

## 9. 디렉토리 구조 (신규)

```
src/breadmind/
├── personal/                    # 새 패키지: 범용 개인 비서
│   ├── __init__.py
│   ├── models.py               # Task, Event, Contact, File, Message 도메인 모델
│   ├── adapters/               # 서비스 어댑터
│   │   ├── __init__.py
│   │   ├── base.py             # ServiceAdapter ABC, AdapterRegistry, SyncResult
│   │   ├── builtin_task.py     # 내장 Task 어댑터 (PostgreSQL)
│   │   ├── builtin_event.py    # 내장 Event 어댑터 (PostgreSQL)
│   │   ├── google_calendar.py  # Google Calendar 어댑터 (Phase 2)
│   │   └── ...                 # Phase 3+에서 추가
│   ├── tools.py                # task_create, event_list 등 LLM 도구 정의
│   ├── proactive.py            # PersonalScheduler (리마인더, 마감 경고)
│   ├── context_provider.py     # PersonalContextProvider (ContextBuilder 플러그인)
│   └── oauth.py                # OAuthManager (Phase 2)
```

기존 파일 수정:
- `memory/profiler.py` — role, exposed_domains, intent_history 추가
- `memory/context_builder.py` — ContextProvider 플러그인 패턴 도입
- `core/intent.py` — 4개 카테고리 추가 + 우선순위 규칙
- `tools/builtin.py` — 새 도구 등록
- `core/bootstrap.py` — DI에 AdapterRegistry, PersonalScheduler 등록

## 10. Phase 계획

### Phase 1: 아키텍처 + 일정/할일 수직 완성
아키텍처 기반과 첫 번째 수직 기능을 함께 구현한다. 의도 확장(SCHEDULE, TASK)은
해당 도구가 동시에 만들어져야 사용자 경험이 성립하므로 분리하지 않는다.

- [ ] `personal/models.py` — 5개 도메인 모델
- [ ] `personal/adapters/base.py` — ServiceAdapter, AdapterRegistry, SyncResult
- [ ] `storage/migrations/` — 새 테이블 생성 SQL (pgcrypto 확장 포함)
- [ ] `personal/adapters/builtin_task.py` — 내장 Task CRUD
- [ ] `personal/adapters/builtin_event.py` — 내장 Event CRUD
- [ ] `personal/tools.py` — task_*, event_*, reminder_set 도구
- [ ] `core/intent.py` 확장 — SCHEDULE, TASK, SEARCH_FILES, CONTACT + 우선순위 규칙
- [ ] `memory/context_builder.py` — ContextProvider 플러그인 패턴 도입
- [ ] `personal/context_provider.py` — PersonalContextProvider
- [ ] `personal/proactive.py` — PersonalScheduler (리마인더, 마감 경고)
- [ ] `memory/profiler.py` 확장 — role, exposed_domains, intent_history 추가
- [ ] `tools/builtin.py` — 새 도구 등록
- [ ] DI 부트스트랩에 AdapterRegistry, PersonalScheduler 등록

### Phase 2: Google Calendar + OAuth 통합
외부 서비스 연동의 첫 번째 검증. OAuth 매니저를 구축하고 Google Calendar로 검증.

- [ ] `personal/oauth.py` — OAuthManager (Google OAuth 2.0)
- [ ] `personal/adapters/google_calendar.py` — Google Calendar 양방향 동기화
- [ ] 동기화 충돌 해결 로직 (last-writer-wins)
- [ ] 웹 UI에 OAuth 인증 플로우 추가

### Phase 3a: Google 서비스 확장
OAuth credential을 공유하여 Google Drive, Contacts를 빠르게 추가.

- [ ] `personal/adapters/google_drive.py` — Google Drive 어댑터
- [ ] `personal/adapters/google_contacts.py` — Google Contacts 어댑터
- [ ] Contact → Semantic Memory KGEntity 승격 로직

### Phase 3b: 생산성 도구 확장
각 서비스의 인증/API가 다르므로 별도 서브 페이즈로 진행.

- [ ] `personal/adapters/notion.py` — Notion 어댑터 (task + file)
- [ ] `personal/adapters/jira.py` — Jira 어댑터 (task)
- [ ] `personal/adapters/github_issues.py` — GitHub Issues 어댑터 (task)

### Phase 4: 체감 우위 확보
- [ ] 크로스 도메인 쿼리 고도화
- [ ] 감정/톤 인식 (urgency 스코어)
- [ ] 능동적 제안 고도화 (패턴 감지, 자동화 제안)
- [ ] Teams, LINE, Matrix, iMessage 게이트웨이
- [ ] Message 도메인 어댑터 (메신저 메시지 검색/요약)
- [ ] 대화 요약에 도메인 엔티티 포함

## 11. OpenClaw 대비 차별화 요약

| 영역 | OpenClaw | BreadMind (목표) |
|------|----------|----------------|
| 기능 연결 | 플러그인 간 독립, 데이터 사일로 | 통합 도메인 모델로 크로스 도메인 쿼리 |
| 메모리 | 파일 기반 4계층 | pgvector + Apache AGE 3계층 + 도메인 엔티티 연동 |
| 능동성 | 수동 (사용자 요청 시만 동작) | 리마인더, 마감 경고, 패턴 감지, 자동화 제안 |
| 사용자 적응 | 단일 프로필 | 역할 자동 감지 (developer/general) + 도구 노출 조절 |
| 인프라 관리 | 없음 | K8s/Proxmox/OpenWrt 자연어 관리 |
| 보안 | PRISM (CVE 발견됨) | 다층 방어 (블랙리스트+승인+쿨다운+감사+HMAC) |
