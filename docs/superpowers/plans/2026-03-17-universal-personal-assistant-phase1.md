# Universal Personal Assistant Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BreadMind에 범용 개인 비서 기능의 아키텍처 기반 + 일정/할일 수직 기능을 구현한다.

**Architecture:** 통합 도메인 모델(Task, Event, Contact, File, Message) 위에 ServiceAdapter 패턴으로 외부 서비스를 추상화. 기존 ContextBuilder에 ContextProvider 플러그인 패턴을 도입하여 도메인 컨텍스트를 주입. PersonalScheduler가 리마인더/마감 경고를 처리.

**Tech Stack:** Python 3.12+, asyncpg (PostgreSQL), python-dateutil (RRULE), FastAPI DI

**Spec:** `docs/superpowers/specs/2026-03-17-universal-personal-assistant-design.md`

---

## File Structure

### 신규 파일
| 파일 | 책임 |
|------|------|
| `src/breadmind/personal/__init__.py` | 패키지 초기화 |
| `src/breadmind/personal/models.py` | 5개 도메인 모델 (Task, Event, Contact, File, Message) |
| `src/breadmind/personal/adapters/__init__.py` | 어댑터 패키지 |
| `src/breadmind/personal/adapters/base.py` | ServiceAdapter ABC, AdapterRegistry, SyncResult |
| `src/breadmind/personal/adapters/builtin_task.py` | 내장 Task CRUD (PostgreSQL) |
| `src/breadmind/personal/adapters/builtin_event.py` | 내장 Event CRUD (PostgreSQL) |
| `src/breadmind/personal/tools.py` | task_*, event_*, reminder_set LLM 도구 |
| `src/breadmind/personal/context_provider.py` | PersonalContextProvider (ContextBuilder 플러그인) |
| `src/breadmind/personal/proactive.py` | PersonalScheduler (리마인더, 마감 경고) |
| `tests/test_personal_models.py` | 도메인 모델 단위 테스트 |
| `tests/test_adapter_registry.py` | AdapterRegistry 단위 테스트 |
| `tests/test_builtin_task_adapter.py` | Task 어댑터 테스트 |
| `tests/test_builtin_event_adapter.py` | Event 어댑터 테스트 |
| `tests/test_personal_tools.py` | LLM 도구 테스트 |
| `tests/test_intent_expansion.py` | 새 의도 카테고리 테스트 |
| `tests/test_context_provider.py` | ContextProvider 패턴 테스트 |
| `tests/test_profiler_extension.py` | UserProfiler 확장 테스트 |
| `tests/test_personal_scheduler.py` | PersonalScheduler 테스트 |

### 수정 파일
| 파일 | 변경 내용 |
|------|----------|
| `src/breadmind/core/intent.py` | 4개 카테고리 추가 + 우선순위 규칙 |
| `src/breadmind/memory/context_builder.py` | ContextProvider 플러그인 인터페이스 도입 |
| `src/breadmind/memory/profiler.py` | role, exposed_domains, intent_history 필드 추가 |
| `src/breadmind/tools/builtin.py` | 개인 비서 도구 등록 |
| `src/breadmind/core/bootstrap.py` | AdapterRegistry, PersonalScheduler DI 등록 |
| `src/breadmind/storage/database.py` | 새 테이블 마이그레이션 추가 |

---

## Chunk 1: Domain Models + Adapter Layer

### Task 1: Domain Models

**Files:**
- Create: `src/breadmind/personal/__init__.py`
- Create: `src/breadmind/personal/models.py`
- Test: `tests/test_personal_models.py`

- [ ] **Step 1: Write failing tests for domain models**

```python
# tests/test_personal_models.py
"""Domain model unit tests."""
from datetime import datetime, timezone
import pytest


def test_task_defaults():
    from breadmind.personal.models import Task

    task = Task(id="t1", title="Buy milk")
    assert task.status == "pending"
    assert task.priority == "medium"
    assert task.source == "builtin"
    assert task.due_at is None
    assert task.tags == []
    assert task.parent_id is None
    assert task.created_at.tzinfo == timezone.utc


def test_task_with_all_fields():
    from breadmind.personal.models import Task

    now = datetime.now(timezone.utc)
    task = Task(
        id="t2",
        title="Deploy v2",
        description="Production deployment",
        status="in_progress",
        priority="urgent",
        due_at=now,
        recurrence="FREQ=WEEKLY;BYDAY=MO",
        tags=["infra", "deploy"],
        source="jira",
        source_id="PROJ-123",
        assignee="alice",
        parent_id="t1",
    )
    assert task.status == "in_progress"
    assert task.source_id == "PROJ-123"
    assert task.recurrence == "FREQ=WEEKLY;BYDAY=MO"


def test_event_defaults():
    from breadmind.personal.models import Event

    now = datetime.now(timezone.utc)
    event = Event(id="e1", title="Standup", start_at=now, end_at=now)
    assert event.all_day is False
    assert event.reminder_minutes == [15]
    assert event.source == "builtin"
    assert event.attendees == []


def test_contact_platform_ids():
    from breadmind.personal.models import Contact

    contact = Contact(
        id="c1",
        name="Bob",
        platform_ids={"telegram": "123", "slack": "U456"},
    )
    assert contact.platform_ids["telegram"] == "123"
    assert contact.email is None


def test_file_defaults():
    from breadmind.personal.models import File

    f = File(id="f1", name="report.pdf", path_or_url="/tmp/report.pdf", mime_type="application/pdf")
    assert f.source == "local"
    assert f.size_bytes == 0


def test_message_defaults():
    from breadmind.personal.models import Message

    msg = Message(id="m1", content="Hello", sender="alice", channel="general", platform="slack")
    assert msg.thread_id is None
    assert msg.attachments == []


def test_parse_recurrence_shorthand():
    from breadmind.personal.models import normalize_recurrence

    assert normalize_recurrence("daily") == "FREQ=DAILY"
    assert normalize_recurrence("weekly") == "FREQ=WEEKLY"
    assert normalize_recurrence("monthly") == "FREQ=MONTHLY"
    assert normalize_recurrence("FREQ=WEEKLY;BYDAY=MO") == "FREQ=WEEKLY;BYDAY=MO"
    assert normalize_recurrence(None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_personal_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'breadmind.personal'`

- [ ] **Step 3: Create package and implement domain models**

```python
# src/breadmind/personal/__init__.py
"""Personal assistant domain — universal domain models and service adapters."""
```

```python
# src/breadmind/personal/models.py
"""Universal domain models for the personal assistant.

All entities use source + source_id for bidirectional sync with external services.
Recurrence fields follow RFC 5545 RRULE format.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_recurrence(value: str | None) -> str | None:
    """Normalize recurrence shorthand to RFC 5545 RRULE format."""
    if value is None:
        return None
    shorthands = {
        "daily": "FREQ=DAILY",
        "weekly": "FREQ=WEEKLY",
        "monthly": "FREQ=MONTHLY",
        "yearly": "FREQ=YEARLY",
    }
    return shorthands.get(value.lower(), value)


@dataclass
class Task:
    id: str
    title: str
    description: str | None = None
    status: Literal["pending", "in_progress", "done", "cancelled"] = "pending"
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    due_at: datetime | None = None
    recurrence: str | None = None
    tags: list[str] = field(default_factory=list)
    source: str = "builtin"
    source_id: str | None = None
    assignee: str | None = None
    parent_id: str | None = None
    user_id: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)


@dataclass
class Event:
    id: str
    title: str
    start_at: datetime
    end_at: datetime
    description: str | None = None
    all_day: bool = False
    location: str | None = None
    attendees: list[str] = field(default_factory=list)
    reminder_minutes: list[int] = field(default_factory=lambda: [15])
    recurrence: str | None = None
    source: str = "builtin"
    source_id: str | None = None
    user_id: str = ""
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class Contact:
    id: str
    name: str
    email: str | None = None
    phone: str | None = None
    platform_ids: dict[str, str] = field(default_factory=dict)
    organization: str | None = None
    tags: list[str] = field(default_factory=list)
    notes: str | None = None
    user_id: str = ""
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class File:
    id: str
    name: str
    path_or_url: str
    mime_type: str
    size_bytes: int = 0
    source: str = "local"
    source_id: str | None = None
    parent_folder: str | None = None
    user_id: str = ""
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class Message:
    id: str
    content: str
    sender: str
    channel: str
    platform: str
    thread_id: str | None = None
    attachments: list[str] = field(default_factory=list)
    user_id: str = ""
    timestamp: datetime = field(default_factory=_utcnow)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_personal_models.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/personal/__init__.py src/breadmind/personal/models.py tests/test_personal_models.py
git commit -m "feat(personal): add universal domain models (Task, Event, Contact, File, Message)"
```

---

### Task 2: Service Adapter Base + Registry

**Files:**
- Create: `src/breadmind/personal/adapters/__init__.py`
- Create: `src/breadmind/personal/adapters/base.py`
- Test: `tests/test_adapter_registry.py`

- [ ] **Step 1: Write failing tests for adapter base and registry**

```python
# tests/test_adapter_registry.py
"""ServiceAdapter and AdapterRegistry unit tests."""
from datetime import datetime, timezone
import pytest


class FakeAdapter:
    """Minimal adapter for testing registry."""

    def __init__(self, domain: str, source: str):
        self._domain = domain
        self._source = source

    @property
    def domain(self) -> str:
        return self._domain

    @property
    def source(self) -> str:
        return self._source

    async def authenticate(self, credentials):
        return True

    async def list_items(self, filters=None, limit=50):
        return []

    async def get_item(self, source_id):
        return None

    async def create_item(self, entity):
        return "fake-id"

    async def update_item(self, source_id, changes):
        return True

    async def delete_item(self, source_id):
        return True

    async def sync(self, since=None):
        from breadmind.personal.adapters.base import SyncResult

        return SyncResult(created=[], updated=[], deleted=[], errors=[], synced_at=datetime.now(timezone.utc))


def test_sync_result_creation():
    from breadmind.personal.adapters.base import SyncResult

    now = datetime.now(timezone.utc)
    result = SyncResult(created=["a"], updated=["b"], deleted=[], errors=[], synced_at=now)
    assert result.created == ["a"]
    assert result.errors == []


def test_registry_register_and_get():
    from breadmind.personal.adapters.base import AdapterRegistry

    registry = AdapterRegistry()
    adapter = FakeAdapter("task", "builtin")
    registry.register(adapter)

    found = registry.get_adapter("task", "builtin")
    assert found is adapter


def test_registry_get_missing_raises():
    from breadmind.personal.adapters.base import AdapterRegistry

    registry = AdapterRegistry()
    with pytest.raises(KeyError):
        registry.get_adapter("task", "nonexistent")


def test_registry_list_by_domain():
    from breadmind.personal.adapters.base import AdapterRegistry

    registry = AdapterRegistry()
    a1 = FakeAdapter("task", "builtin")
    a2 = FakeAdapter("task", "jira")
    a3 = FakeAdapter("event", "builtin")
    registry.register(a1)
    registry.register(a2)
    registry.register(a3)

    task_adapters = registry.list_adapters("task")
    assert len(task_adapters) == 2

    all_adapters = registry.list_adapters()
    assert len(all_adapters) == 3


def test_registry_duplicate_replaces():
    from breadmind.personal.adapters.base import AdapterRegistry

    registry = AdapterRegistry()
    a1 = FakeAdapter("task", "builtin")
    a2 = FakeAdapter("task", "builtin")
    registry.register(a1)
    registry.register(a2)

    assert registry.get_adapter("task", "builtin") is a2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_adapter_registry.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement ServiceAdapter ABC and AdapterRegistry**

```python
# src/breadmind/personal/adapters/__init__.py
"""Service adapters for external service integration."""
```

```python
# src/breadmind/personal/adapters/base.py
"""Service adapter interfaces and registry.

ServiceAdapter defines the contract all external service integrations must follow.
AdapterRegistry manages adapter instances by (domain, source) key pairs.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SyncResult:
    """Result of a bidirectional sync operation."""

    created: list[str]
    updated: list[str]
    deleted: list[str]
    errors: list[str]
    synced_at: datetime = field(default_factory=_utcnow)


class ServiceAdapter(ABC):
    """Abstract base for all external service adapters.

    Each adapter handles one (domain, source) combination.
    Domain: "task", "event", "contact", "file", "message"
    Source: "builtin", "google_calendar", "notion", etc.
    """

    @property
    @abstractmethod
    def domain(self) -> str: ...

    @property
    @abstractmethod
    def source(self) -> str: ...

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
    async def sync(self, since: datetime | None = None) -> SyncResult: ...


class AdapterRegistry:
    """Registry for service adapters, keyed by (domain, source)."""

    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str], ServiceAdapter] = {}

    def register(self, adapter: ServiceAdapter) -> None:
        key = (adapter.domain, adapter.source)
        self._adapters[key] = adapter

    def get_adapter(self, domain: str, source: str) -> ServiceAdapter:
        key = (domain, source)
        if key not in self._adapters:
            raise KeyError(f"No adapter registered for ({domain}, {source})")
        return self._adapters[key]

    def list_adapters(self, domain: str | None = None) -> list[ServiceAdapter]:
        if domain is None:
            return list(self._adapters.values())
        return [a for (d, _), a in self._adapters.items() if d == domain]

    async def sync_all(self, domain: str | None = None) -> dict[str, SyncResult]:
        """Run sync on all adapters (or filtered by domain)."""
        results: dict[str, SyncResult] = {}
        for adapter in self.list_adapters(domain):
            key = f"{adapter.domain}:{adapter.source}"
            results[key] = await adapter.sync()
        return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_adapter_registry.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/personal/adapters/__init__.py src/breadmind/personal/adapters/base.py tests/test_adapter_registry.py
git commit -m "feat(personal): add ServiceAdapter ABC and AdapterRegistry"
```

---

### Task 3: Database Migration

**Files:**
- Modify: `src/breadmind/storage/database.py` — `_migrate()` 메서드에 새 테이블 추가

- [ ] **Step 1: Read current migration code**

Read `src/breadmind/storage/database.py` and find the `_migrate()` method. Note the existing table creation pattern (uses `CREATE TABLE IF NOT EXISTS`).

- [ ] **Step 2: Add new tables to migration**

`database.py`의 `_migrate()` 메서드 끝에 다음 SQL을 추가:

```sql
-- Personal assistant tables
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS tasks (
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

CREATE TABLE IF NOT EXISTS events (
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

CREATE TABLE IF NOT EXISTS contacts (
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

CREATE TABLE IF NOT EXISTS files_meta (
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

CREATE TABLE IF NOT EXISTS sync_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    adapter_domain VARCHAR(50) NOT NULL,
    adapter_source VARCHAR(50) NOT NULL,
    user_id TEXT NOT NULL,
    last_synced_at TIMESTAMPTZ,
    sync_token TEXT,
    UNIQUE(adapter_domain, adapter_source, user_id)
);

CREATE TABLE IF NOT EXISTS sync_conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_table VARCHAR(50) NOT NULL,
    entity_id UUID NOT NULL,
    local_data JSONB NOT NULL,
    remote_data JSONB NOT NULL,
    resolution VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON tasks(user_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_due_at ON tasks(due_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_events_user_time ON events(user_id, start_at);
CREATE INDEX IF NOT EXISTS idx_contacts_user ON contacts(user_id);
CREATE INDEX IF NOT EXISTS idx_files_meta_user_source ON files_meta(user_id, source);
```

Note: 테이블명 `files` → `files_meta`로 변경 (PostgreSQL에서 `files`는 예약어 충돌 위험).

- [ ] **Step 3: Commit**

```bash
git add src/breadmind/storage/database.py
git commit -m "feat(storage): add personal assistant tables migration"
```

---

### Task 4: Builtin Task Adapter

**Files:**
- Create: `src/breadmind/personal/adapters/builtin_task.py`
- Test: `tests/test_builtin_task_adapter.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_builtin_task_adapter.py
"""BuiltinTaskAdapter unit tests using mock database."""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
import pytest
import pytest_asyncio


@pytest.fixture
def mock_db():
    """Mock database with acquire() context manager."""
    db = AsyncMock()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock()

    class AcquireCM:
        async def __aenter__(self):
            return conn
        async def __aexit__(self, *args):
            pass

    db.acquire = MagicMock(return_value=AcquireCM())
    return db, conn


@pytest.mark.asyncio
async def test_create_task(mock_db):
    from breadmind.personal.adapters.builtin_task import BuiltinTaskAdapter
    from breadmind.personal.models import Task

    db, conn = mock_db
    conn.fetchrow.return_value = {"id": "00000000-0000-0000-0000-000000000001"}
    adapter = BuiltinTaskAdapter(db)

    task = Task(id="", title="Buy milk", user_id="alice")
    result_id = await adapter.create_item(task)
    assert result_id is not None
    conn.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_list_tasks_no_filters(mock_db):
    from breadmind.personal.adapters.builtin_task import BuiltinTaskAdapter

    db, conn = mock_db
    conn.fetch.return_value = [
        {"id": "id1", "title": "Task 1", "description": None, "status": "pending",
         "priority": "medium", "due_at": None, "recurrence": None, "tags": [],
         "source": "builtin", "source_id": None, "assignee": None, "parent_id": None,
         "user_id": "alice", "created_at": datetime.now(timezone.utc),
         "updated_at": datetime.now(timezone.utc)},
    ]
    adapter = BuiltinTaskAdapter(db)
    tasks = await adapter.list_items(filters={"user_id": "alice"})
    assert len(tasks) == 1
    assert tasks[0].title == "Task 1"


@pytest.mark.asyncio
async def test_update_task(mock_db):
    from breadmind.personal.adapters.builtin_task import BuiltinTaskAdapter

    db, conn = mock_db
    conn.execute.return_value = "UPDATE 1"
    adapter = BuiltinTaskAdapter(db)

    result = await adapter.update_item("task-id-1", {"status": "done", "title": "Updated"})
    assert result is True


@pytest.mark.asyncio
async def test_delete_task(mock_db):
    from breadmind.personal.adapters.builtin_task import BuiltinTaskAdapter

    db, conn = mock_db
    conn.execute.return_value = "DELETE 1"
    adapter = BuiltinTaskAdapter(db)

    result = await adapter.delete_item("task-id-1")
    assert result is True


@pytest.mark.asyncio
async def test_list_tasks_with_status_filter(mock_db):
    from breadmind.personal.adapters.builtin_task import BuiltinTaskAdapter

    db, conn = mock_db
    conn.fetch.return_value = []
    adapter = BuiltinTaskAdapter(db)

    await adapter.list_items(filters={"user_id": "alice", "status": "done"})
    # Verify the query was called (details checked by integration test)
    conn.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_list_tasks_with_due_before_filter(mock_db):
    from breadmind.personal.adapters.builtin_task import BuiltinTaskAdapter

    db, conn = mock_db
    conn.fetch.return_value = []
    adapter = BuiltinTaskAdapter(db)

    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    await adapter.list_items(filters={"user_id": "alice", "due_before": tomorrow})
    conn.fetch.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_builtin_task_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement BuiltinTaskAdapter**

```python
# src/breadmind/personal/adapters/builtin_task.py
"""Built-in Task adapter backed by PostgreSQL.

Handles CRUD operations for tasks stored in the local database.
Filters: user_id (required), status, priority, due_before, tags.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from breadmind.personal.adapters.base import ServiceAdapter, SyncResult
from breadmind.personal.models import Task


class BuiltinTaskAdapter(ServiceAdapter):

    def __init__(self, db: Any) -> None:
        self._db = db

    @property
    def domain(self) -> str:
        return "task"

    @property
    def source(self) -> str:
        return "builtin"

    async def authenticate(self, credentials: dict) -> bool:
        return True  # builtin needs no auth

    async def list_items(self, filters: dict | None = None, limit: int = 50) -> list[Task]:
        filters = filters or {}
        user_id = filters.get("user_id", "")

        query = "SELECT * FROM tasks WHERE user_id = $1"
        params: list[Any] = [user_id]
        idx = 2

        if "status" in filters:
            query += f" AND status = ${idx}"
            params.append(filters["status"])
            idx += 1

        if "priority" in filters:
            query += f" AND priority = ${idx}"
            params.append(filters["priority"])
            idx += 1

        if "due_before" in filters:
            query += f" AND due_at IS NOT NULL AND due_at <= ${idx}"
            params.append(filters["due_before"])
            idx += 1

        if "tags" in filters:
            query += f" AND tags && ${idx}"
            params.append(filters["tags"])
            idx += 1

        query += f" ORDER BY created_at DESC LIMIT ${idx}"
        params.append(limit)

        async with self._db.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [self._row_to_task(row) for row in rows]

    async def get_item(self, source_id: str) -> Task | None:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", source_id)
        return self._row_to_task(row) if row else None

    async def create_item(self, entity: Task) -> str:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO tasks (title, description, status, priority, due_at,
                   recurrence, tags, source, source_id, assignee, parent_id, user_id)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                   RETURNING id""",
                entity.title,
                entity.description,
                entity.status,
                entity.priority,
                entity.due_at,
                entity.recurrence,
                entity.tags,
                entity.source,
                entity.source_id,
                entity.assignee,
                entity.parent_id,
                entity.user_id,
            )
        return str(row["id"])

    async def update_item(self, source_id: str, changes: dict) -> bool:
        if not changes:
            return False
        allowed = {"title", "description", "status", "priority", "due_at", "recurrence", "tags", "assignee"}
        filtered = {k: v for k, v in changes.items() if k in allowed}
        if not filtered:
            return False

        filtered["updated_at"] = datetime.now(timezone.utc)
        sets = [f"{k} = ${i+2}" for i, k in enumerate(filtered)]
        query = f"UPDATE tasks SET {', '.join(sets)} WHERE id = $1"
        params = [source_id, *filtered.values()]

        async with self._db.acquire() as conn:
            await conn.execute(query, *params)
        return True

    async def delete_item(self, source_id: str) -> bool:
        async with self._db.acquire() as conn:
            await conn.execute("DELETE FROM tasks WHERE id = $1", source_id)
        return True

    async def sync(self, since: datetime | None = None) -> SyncResult:
        # Builtin adapter is the source of truth — no external sync needed
        return SyncResult(
            created=[], updated=[], deleted=[], errors=[],
            synced_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _row_to_task(row: dict) -> Task:
        return Task(
            id=str(row["id"]),
            title=row["title"],
            description=row.get("description"),
            status=row.get("status", "pending"),
            priority=row.get("priority", "medium"),
            due_at=row.get("due_at"),
            recurrence=row.get("recurrence"),
            tags=row.get("tags", []),
            source=row.get("source", "builtin"),
            source_id=row.get("source_id"),
            assignee=row.get("assignee"),
            parent_id=str(row["parent_id"]) if row.get("parent_id") else None,
            user_id=row.get("user_id", ""),
            created_at=row.get("created_at", datetime.now(timezone.utc)),
            updated_at=row.get("updated_at", datetime.now(timezone.utc)),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_builtin_task_adapter.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/personal/adapters/builtin_task.py tests/test_builtin_task_adapter.py
git commit -m "feat(personal): add BuiltinTaskAdapter with PostgreSQL CRUD"
```

---

### Task 5: Builtin Event Adapter

**Files:**
- Create: `src/breadmind/personal/adapters/builtin_event.py`
- Test: `tests/test_builtin_event_adapter.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_builtin_event_adapter.py
"""BuiltinEventAdapter unit tests."""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
import pytest


@pytest.fixture
def mock_db():
    db = AsyncMock()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock()

    class AcquireCM:
        async def __aenter__(self):
            return conn
        async def __aexit__(self, *args):
            pass

    db.acquire = MagicMock(return_value=AcquireCM())
    return db, conn


@pytest.mark.asyncio
async def test_create_event(mock_db):
    from breadmind.personal.adapters.builtin_event import BuiltinEventAdapter
    from breadmind.personal.models import Event

    db, conn = mock_db
    conn.fetchrow.return_value = {"id": "00000000-0000-0000-0000-000000000001"}
    adapter = BuiltinEventAdapter(db)

    now = datetime.now(timezone.utc)
    event = Event(id="", title="Standup", start_at=now, end_at=now + timedelta(minutes=30), user_id="alice")
    result_id = await adapter.create_item(event)
    assert result_id is not None


@pytest.mark.asyncio
async def test_list_events_time_range(mock_db):
    from breadmind.personal.adapters.builtin_event import BuiltinEventAdapter

    db, conn = mock_db
    now = datetime.now(timezone.utc)
    conn.fetch.return_value = [
        {"id": "e1", "title": "Meeting", "description": None, "start_at": now,
         "end_at": now + timedelta(hours=1), "all_day": False, "location": None,
         "attendees": [], "reminder_minutes": [15], "recurrence": None,
         "source": "builtin", "source_id": None, "user_id": "alice",
         "created_at": now},
    ]
    adapter = BuiltinEventAdapter(db)
    events = await adapter.list_items(filters={
        "user_id": "alice",
        "start_after": now,
        "start_before": now + timedelta(days=7),
    })
    assert len(events) == 1
    assert events[0].title == "Meeting"


@pytest.mark.asyncio
async def test_update_event(mock_db):
    from breadmind.personal.adapters.builtin_event import BuiltinEventAdapter

    db, conn = mock_db
    adapter = BuiltinEventAdapter(db)
    result = await adapter.update_item("e1", {"title": "Updated Meeting", "location": "Room A"})
    assert result is True


@pytest.mark.asyncio
async def test_delete_event(mock_db):
    from breadmind.personal.adapters.builtin_event import BuiltinEventAdapter

    db, conn = mock_db
    adapter = BuiltinEventAdapter(db)
    result = await adapter.delete_item("e1")
    assert result is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_builtin_event_adapter.py -v`
Expected: FAIL

- [ ] **Step 3: Implement BuiltinEventAdapter**

```python
# src/breadmind/personal/adapters/builtin_event.py
"""Built-in Event adapter backed by PostgreSQL.

Handles CRUD for calendar events. Filters: user_id, start_after, start_before.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from breadmind.personal.adapters.base import ServiceAdapter, SyncResult
from breadmind.personal.models import Event


class BuiltinEventAdapter(ServiceAdapter):

    def __init__(self, db: Any) -> None:
        self._db = db

    @property
    def domain(self) -> str:
        return "event"

    @property
    def source(self) -> str:
        return "builtin"

    async def authenticate(self, credentials: dict) -> bool:
        return True

    async def list_items(self, filters: dict | None = None, limit: int = 50) -> list[Event]:
        filters = filters or {}
        user_id = filters.get("user_id", "")

        query = "SELECT * FROM events WHERE user_id = $1"
        params: list[Any] = [user_id]
        idx = 2

        if "start_after" in filters:
            query += f" AND start_at >= ${idx}"
            params.append(filters["start_after"])
            idx += 1

        if "start_before" in filters:
            query += f" AND start_at <= ${idx}"
            params.append(filters["start_before"])
            idx += 1

        query += f" ORDER BY start_at ASC LIMIT ${idx}"
        params.append(limit)

        async with self._db.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [self._row_to_event(row) for row in rows]

    async def get_item(self, source_id: str) -> Event | None:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM events WHERE id = $1", source_id)
        return self._row_to_event(row) if row else None

    async def create_item(self, entity: Event) -> str:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO events (title, description, start_at, end_at, all_day,
                   location, attendees, reminder_minutes, recurrence, source, source_id, user_id)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                   RETURNING id""",
                entity.title,
                entity.description,
                entity.start_at,
                entity.end_at,
                entity.all_day,
                entity.location,
                entity.attendees,
                entity.reminder_minutes,
                entity.recurrence,
                entity.source,
                entity.source_id,
                entity.user_id,
            )
        return str(row["id"])

    async def update_item(self, source_id: str, changes: dict) -> bool:
        if not changes:
            return False
        allowed = {"title", "description", "start_at", "end_at", "all_day", "location",
                    "attendees", "reminder_minutes", "recurrence"}
        filtered = {k: v for k, v in changes.items() if k in allowed}
        if not filtered:
            return False

        sets = [f"{k} = ${i+2}" for i, k in enumerate(filtered)]
        query = f"UPDATE events SET {', '.join(sets)} WHERE id = $1"
        params = [source_id, *filtered.values()]

        async with self._db.acquire() as conn:
            await conn.execute(query, *params)
        return True

    async def delete_item(self, source_id: str) -> bool:
        async with self._db.acquire() as conn:
            await conn.execute("DELETE FROM events WHERE id = $1", source_id)
        return True

    async def sync(self, since: datetime | None = None) -> SyncResult:
        return SyncResult(
            created=[], updated=[], deleted=[], errors=[],
            synced_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _row_to_event(row: dict) -> Event:
        return Event(
            id=str(row["id"]),
            title=row["title"],
            description=row.get("description"),
            start_at=row["start_at"],
            end_at=row["end_at"],
            all_day=row.get("all_day", False),
            location=row.get("location"),
            attendees=row.get("attendees", []),
            reminder_minutes=row.get("reminder_minutes", [15]),
            recurrence=row.get("recurrence"),
            source=row.get("source", "builtin"),
            source_id=row.get("source_id"),
            user_id=row.get("user_id", ""),
            created_at=row.get("created_at", datetime.now(timezone.utc)),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_builtin_event_adapter.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/personal/adapters/builtin_event.py tests/test_builtin_event_adapter.py
git commit -m "feat(personal): add BuiltinEventAdapter with PostgreSQL CRUD"
```

---

## Chunk 2: Intent Expansion + LLM Tools

### Task 6: Intent Classification Expansion

**Files:**
- Modify: `src/breadmind/core/intent.py`
- Test: `tests/test_intent_expansion.py`

- [ ] **Step 1: Write failing tests for new intent categories**

```python
# tests/test_intent_expansion.py
"""Tests for expanded intent categories (SCHEDULE, TASK, SEARCH_FILES, CONTACT)."""
import pytest


def test_schedule_intent_korean():
    from breadmind.core.intent import classify, IntentCategory

    result = classify("내일 3시에 회의 잡아줘")
    assert result.category == IntentCategory.SCHEDULE
    assert "event_create" in result.tool_hints


def test_schedule_intent_english():
    from breadmind.core.intent import classify, IntentCategory

    result = classify("Schedule a meeting for tomorrow at 3pm")
    assert result.category == IntentCategory.SCHEDULE


def test_task_intent():
    from breadmind.core.intent import classify, IntentCategory

    result = classify("할 일 목록 보여줘")
    assert result.category == IntentCategory.TASK
    assert "task_list" in result.tool_hints


def test_task_create_intent():
    from breadmind.core.intent import classify, IntentCategory

    result = classify("우유 사기를 할 일에 추가해줘")
    assert result.category == IntentCategory.TASK
    assert "task_create" in result.tool_hints


def test_contact_intent():
    from breadmind.core.intent import classify, IntentCategory

    result = classify("김철수 연락처 찾아줘")
    assert result.category == IntentCategory.CONTACT
    assert "contact_search" in result.tool_hints


def test_search_files_intent():
    from breadmind.core.intent import classify, IntentCategory

    result = classify("보고서 파일 찾아줘")
    assert result.category == IntentCategory.SEARCH_FILES
    assert "file_search" in result.tool_hints


def test_task_beats_execute():
    """TASK should win over EXECUTE when domain keyword is present."""
    from breadmind.core.intent import classify, IntentCategory

    result = classify("할 일 생성해줘")
    assert result.category == IntentCategory.TASK


def test_schedule_beats_execute():
    """SCHEDULE should win over EXECUTE when domain keyword is present."""
    from breadmind.core.intent import classify, IntentCategory

    result = classify("일정 추가해줘")
    assert result.category == IntentCategory.SCHEDULE


def test_existing_intents_unchanged():
    """Existing intent categories should still work."""
    from breadmind.core.intent import classify, IntentCategory

    # QUERY
    result = classify("서버 상태 확인해줘")
    assert result.category == IntentCategory.QUERY

    # CHAT
    result = classify("안녕하세요")
    assert result.category == IntentCategory.CHAT

    # DIAGNOSE
    result = classify("에러가 발생했어 분석해줘")
    assert result.category == IntentCategory.DIAGNOSE


def test_think_budgets_for_new_categories():
    from breadmind.core.intent import classify, IntentCategory

    # get_think_budget takes an Intent object, not IntentCategory
    schedule = classify("회의 일정 잡아줘")
    assert schedule.category == IntentCategory.SCHEDULE

    from breadmind.core.intent import get_think_budget
    budget = get_think_budget(schedule)
    assert budget > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_intent_expansion.py -v`
Expected: FAIL — `AttributeError: 'IntentCategory' has no attribute 'SCHEDULE'`

- [ ] **Step 3: Modify intent.py**

Read `src/breadmind/core/intent.py` first. Then make these changes:

1. Add to `IntentCategory` enum:
```python
    SCHEDULE = "schedule"       # 일정/캘린더 관리
    TASK = "task"               # 할 일 관리
    SEARCH_FILES = "search_files"  # 파일 검색
    CONTACT = "contact"         # 연락처 관리
```

2. Add patterns to `_PATTERNS` list. The existing `_PATTERNS` uses `list[tuple[re.Pattern, IntentCategory, float]]` format with pre-compiled regex. Add new patterns BEFORE existing EXECUTE patterns so domain keywords get scored first:

```python
# Add these entries to the _PATTERNS list (using re.compile, same as existing patterns):
(re.compile(r"일정|회의|약속|캘린더|calendar|schedule|meeting|언제.*시간|예약", re.I), IntentCategory.SCHEDULE, 0.7),
(re.compile(r"할\s*일|해야\s*할|완료|체크|리마인더|마감|todo|task|remind", re.I), IntentCategory.TASK, 0.7),
(re.compile(r"파일|문서|드라이브|drive|document|다운로드|download", re.I), IntentCategory.SEARCH_FILES, 0.6),
(re.compile(r"연락처|전화번호|이메일\s*주소|담당자|contact", re.I), IntentCategory.CONTACT, 0.7),
```

3. Add to `_TOOL_HINTS` dict:
```python
    IntentCategory.SCHEDULE: {"event_create", "event_list", "event_update", "event_delete"},
    IntentCategory.TASK: {"task_create", "task_list", "task_update", "task_delete", "reminder_set"},
    IntentCategory.SEARCH_FILES: {"file_search", "file_read", "file_list"},
    IntentCategory.CONTACT: {"contact_search", "contact_create"},
```

4. Add to `_THINK_BUDGETS` dict:
```python
    IntentCategory.SCHEDULE: 5120,
    IntentCategory.TASK: 5120,
    IntentCategory.SEARCH_FILES: 5120,
    IntentCategory.CONTACT: 3072,
```

5. Modify `classify()` to apply priority when domain categories tie with EXECUTE.

Add priority list at module level:
```python
_CATEGORY_PRIORITY: dict[IntentCategory, int] = {
    IntentCategory.SCHEDULE: 0,
    IntentCategory.TASK: 1,
    IntentCategory.CONTACT: 2,
    IntentCategory.SEARCH_FILES: 3,
    IntentCategory.DIAGNOSE: 4,
    IntentCategory.EXECUTE: 5,
    IntentCategory.CONFIGURE: 6,
    IntentCategory.QUERY: 7,
    IntentCategory.LEARN: 8,
    IntentCategory.CHAT: 9,
}
```

In `classify()`, replace the simple `max(scores, key=scores.get)` with:
```python
    # Sort candidates by (score DESC, priority ASC) to break ties
    sorted_candidates = sorted(
        scores.items(),
        key=lambda item: (-item[1], _CATEGORY_PRIORITY.get(item[0], 99)),
    )
    best_category = sorted_candidates[0][0]
    best_score = sorted_candidates[0][1]
```

This ensures that when TASK and EXECUTE both score 0.7 (e.g., "할 일 생성해줘"), TASK wins because it has lower priority number (higher priority).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_intent_expansion.py -v`
Expected: All 11 tests PASS

- [ ] **Step 5: Run existing intent tests to verify no regression**

Run: `python -m pytest tests/ -k "intent" -v`
Expected: All existing + new tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/breadmind/core/intent.py tests/test_intent_expansion.py
git commit -m "feat(intent): add SCHEDULE, TASK, SEARCH_FILES, CONTACT categories with priority rules"
```

---

### Task 7: Personal Assistant LLM Tools

**Files:**
- Create: `src/breadmind/personal/tools.py`
- Test: `tests/test_personal_tools.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_personal_tools.py
"""Tests for personal assistant LLM tool functions."""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.fixture
def mock_adapter_registry():
    from breadmind.personal.adapters.base import AdapterRegistry
    registry = AdapterRegistry()

    task_adapter = AsyncMock()
    task_adapter.domain = "task"
    task_adapter.source = "builtin"
    task_adapter.create_item = AsyncMock(return_value="new-task-id")
    task_adapter.list_items = AsyncMock(return_value=[])
    task_adapter.update_item = AsyncMock(return_value=True)
    task_adapter.delete_item = AsyncMock(return_value=True)
    registry.register(task_adapter)

    event_adapter = AsyncMock()
    event_adapter.domain = "event"
    event_adapter.source = "builtin"
    event_adapter.create_item = AsyncMock(return_value="new-event-id")
    event_adapter.list_items = AsyncMock(return_value=[])
    event_adapter.update_item = AsyncMock(return_value=True)
    event_adapter.delete_item = AsyncMock(return_value=True)
    registry.register(event_adapter)

    return registry


@pytest.mark.asyncio
async def test_task_create(mock_adapter_registry):
    from breadmind.personal.tools import task_create

    result = await task_create(
        title="Buy milk",
        registry=mock_adapter_registry,
        user_id="alice",
    )
    assert "new-task-id" in result
    mock_adapter_registry.get_adapter("task", "builtin").create_item.assert_called_once()


@pytest.mark.asyncio
async def test_task_list(mock_adapter_registry):
    from breadmind.personal.tools import task_list

    result = await task_list(registry=mock_adapter_registry, user_id="alice")
    assert "할 일" in result or "없" in result  # Empty list message


@pytest.mark.asyncio
async def test_task_update(mock_adapter_registry):
    from breadmind.personal.tools import task_update

    result = await task_update(
        task_id="t1",
        status="done",
        registry=mock_adapter_registry,
    )
    assert "완료" in result or "업데이트" in result or "update" in result.lower()


@pytest.mark.asyncio
async def test_task_delete(mock_adapter_registry):
    from breadmind.personal.tools import task_delete

    result = await task_delete(task_id="t1", registry=mock_adapter_registry)
    assert "삭제" in result or "delete" in result.lower()


@pytest.mark.asyncio
async def test_event_create(mock_adapter_registry):
    from breadmind.personal.tools import event_create

    result = await event_create(
        title="Standup",
        start_at="2026-03-18T09:00:00Z",
        registry=mock_adapter_registry,
        user_id="alice",
    )
    assert "new-event-id" in result


@pytest.mark.asyncio
async def test_event_list(mock_adapter_registry):
    from breadmind.personal.tools import event_list

    result = await event_list(registry=mock_adapter_registry, user_id="alice")
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_reminder_set(mock_adapter_registry):
    from breadmind.personal.tools import reminder_set

    result = await reminder_set(
        message="Take medicine",
        remind_at="2026-03-18T18:00:00Z",
        registry=mock_adapter_registry,
        user_id="alice",
    )
    # reminder_set creates an Event internally
    mock_adapter_registry.get_adapter("event", "builtin").create_item.assert_called_once()
    assert "리마인더" in result or "reminder" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_personal_tools.py -v`
Expected: FAIL

- [ ] **Step 3: Implement personal tools**

```python
# src/breadmind/personal/tools.py
"""LLM tool functions for personal assistant features.

These functions are registered as LLM-callable tools. They bridge
the LLM's tool calls to the adapter registry for actual CRUD operations.

DEPENDENCY INJECTION:
  - `registry` and `user_id` are NOT exposed to the LLM as tool parameters.
  - They are injected at call time using `functools.partial` in `register_personal_tools()`.
  - The @tool decorator's auto-schema skips parameters that have non-JSON types (like AdapterRegistry).
  - The ToolRegistry._validate_and_coerce_arguments() already skips unknown params.
  - So the LLM only sees: title, description, due_at, priority, tags, etc.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any

from breadmind.personal.adapters.base import AdapterRegistry
from breadmind.personal.models import Task, Event, normalize_recurrence


async def task_create(
    title: str,
    registry: AdapterRegistry,
    user_id: str,
    description: str | None = None,
    due_at: str | None = None,
    priority: str = "medium",
    tags: str | None = None,
) -> str:
    """할 일을 생성합니다."""
    parsed_due = _parse_datetime(due_at) if due_at else None
    parsed_tags = [t.strip() for t in tags.split(",")] if tags else []

    task = Task(
        id="",
        title=title,
        description=description,
        due_at=parsed_due,
        priority=priority,
        tags=parsed_tags,
        user_id=user_id,
    )
    adapter = registry.get_adapter("task", "builtin")
    task_id = await adapter.create_item(task)
    due_str = f" (마감: {parsed_due.strftime('%Y-%m-%d %H:%M')})" if parsed_due else ""
    return f"할 일 생성 완료: '{title}'{due_str} [ID: {task_id}]"


async def task_list(
    registry: AdapterRegistry,
    user_id: str,
    status: str | None = None,
    priority: str | None = None,
    due_before: str | None = None,
    tags: str | None = None,
) -> str:
    """할 일 목록을 조회합니다."""
    filters: dict[str, Any] = {"user_id": user_id}
    if status:
        filters["status"] = status
    if priority:
        filters["priority"] = priority
    if due_before:
        filters["due_before"] = _parse_datetime(due_before)
    if tags:
        filters["tags"] = [t.strip() for t in tags.split(",")]

    adapter = registry.get_adapter("task", "builtin")
    tasks = await adapter.list_items(filters=filters)

    if not tasks:
        return "할 일이 없습니다."

    lines = ["📋 할 일 목록:"]
    for t in tasks:
        status_icon = {"pending": "⬜", "in_progress": "🔵", "done": "✅", "cancelled": "❌"}.get(t.status, "⬜")
        due_str = f" (마감: {t.due_at.strftime('%m/%d %H:%M')})" if t.due_at else ""
        priority_str = f" [{t.priority}]" if t.priority != "medium" else ""
        lines.append(f"  {status_icon} {t.title}{priority_str}{due_str} [ID: {t.id[:8]}]")
    return "\n".join(lines)


async def task_update(
    task_id: str,
    registry: AdapterRegistry,
    status: str | None = None,
    title: str | None = None,
    due_at: str | None = None,
    priority: str | None = None,
) -> str:
    """할 일을 수정합니다."""
    changes: dict[str, Any] = {}
    if status:
        changes["status"] = status
    if title:
        changes["title"] = title
    if due_at:
        changes["due_at"] = _parse_datetime(due_at)
    if priority:
        changes["priority"] = priority

    adapter = registry.get_adapter("task", "builtin")
    await adapter.update_item(task_id, changes)
    return f"할 일 업데이트 완료 [ID: {task_id[:8]}]"


async def task_delete(task_id: str, registry: AdapterRegistry) -> str:
    """할 일을 삭제합니다."""
    adapter = registry.get_adapter("task", "builtin")
    await adapter.delete_item(task_id)
    return f"할 일 삭제 완료 [ID: {task_id[:8]}]"


async def event_create(
    title: str,
    start_at: str,
    registry: AdapterRegistry,
    user_id: str,
    end_at: str | None = None,
    all_day: bool = False,
    location: str | None = None,
    attendees: str | None = None,
    reminder_minutes: str | None = None,
    recurrence: str | None = None,
) -> str:
    """일정을 생성합니다."""
    parsed_start = _parse_datetime(start_at)
    parsed_end = _parse_datetime(end_at) if end_at else parsed_start + timedelta(hours=1)
    parsed_attendees = [a.strip() for a in attendees.split(",")] if attendees else []
    parsed_reminders = [int(m) for m in reminder_minutes.split(",")] if reminder_minutes else [15]

    event = Event(
        id="",
        title=title,
        start_at=parsed_start,
        end_at=parsed_end,
        all_day=all_day,
        location=location,
        attendees=parsed_attendees,
        reminder_minutes=parsed_reminders,
        recurrence=normalize_recurrence(recurrence),
        user_id=user_id,
    )
    adapter = registry.get_adapter("event", "builtin")
    event_id = await adapter.create_item(event)
    return f"일정 생성 완료: '{title}' ({parsed_start.strftime('%m/%d %H:%M')}~{parsed_end.strftime('%H:%M')}) [ID: {event_id}]"


async def event_list(
    registry: AdapterRegistry,
    user_id: str,
    start_after: str | None = None,
    start_before: str | None = None,
) -> str:
    """일정 목록을 조회합니다."""
    filters: dict[str, Any] = {"user_id": user_id}
    if start_after:
        filters["start_after"] = _parse_datetime(start_after)
    else:
        filters["start_after"] = datetime.now(timezone.utc)
    if start_before:
        filters["start_before"] = _parse_datetime(start_before)
    else:
        filters["start_before"] = datetime.now(timezone.utc) + timedelta(days=7)

    adapter = registry.get_adapter("event", "builtin")
    events = await adapter.list_items(filters=filters)

    if not events:
        return "예정된 일정이 없습니다."

    lines = ["📅 일정 목록:"]
    for e in events:
        time_str = f"{e.start_at.strftime('%m/%d %H:%M')}~{e.end_at.strftime('%H:%M')}"
        loc_str = f" @ {e.location}" if e.location else ""
        lines.append(f"  • {e.title} ({time_str}{loc_str}) [ID: {e.id[:8]}]")
    return "\n".join(lines)


async def event_update(
    event_id: str,
    registry: AdapterRegistry,
    title: str | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
    location: str | None = None,
) -> str:
    """일정을 수정합니다."""
    changes: dict[str, Any] = {}
    if title:
        changes["title"] = title
    if start_at:
        changes["start_at"] = _parse_datetime(start_at)
    if end_at:
        changes["end_at"] = _parse_datetime(end_at)
    if location:
        changes["location"] = location

    adapter = registry.get_adapter("event", "builtin")
    await adapter.update_item(event_id, changes)
    return f"일정 업데이트 완료 [ID: {event_id[:8]}]"


async def event_delete(event_id: str, registry: AdapterRegistry) -> str:
    """일정을 삭제합니다."""
    adapter = registry.get_adapter("event", "builtin")
    await adapter.delete_item(event_id)
    return f"일정 삭제 완료 [ID: {event_id[:8]}]"


async def reminder_set(
    message: str,
    remind_at: str,
    registry: AdapterRegistry,
    user_id: str,
    recurrence: str | None = None,
) -> str:
    """리마인더를 설정합니다. 내부적으로 Event로 저장합니다."""
    parsed_time = _parse_datetime(remind_at)
    event = Event(
        id="",
        title=f"🔔 {message}",
        start_at=parsed_time,
        end_at=parsed_time,
        reminder_minutes=[0],
        recurrence=normalize_recurrence(recurrence),
        user_id=user_id,
    )
    adapter = registry.get_adapter("event", "builtin")
    event_id = await adapter.create_item(event)
    recur_str = f" (반복: {recurrence})" if recurrence else ""
    return f"리마인더 설정 완료: '{message}' ({parsed_time.strftime('%m/%d %H:%M')}){recur_str} [ID: {event_id}]"


def _parse_datetime(value: str) -> datetime:
    """Parse ISO 8601 datetime string, ensuring UTC timezone."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Invalid datetime format: '{value}'. Use ISO 8601 (e.g., 2026-03-18T09:00:00Z)")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def register_personal_tools(tool_registry, adapter_registry: AdapterRegistry, user_id: str = "default") -> None:
    """Register personal tools with dependency injection via functools.partial.

    This binds `registry` and `user_id` so the LLM only sees the user-facing params.
    The @tool decorator will generate schema from the partial's remaining params.
    """
    from breadmind.tools.registry import tool

    tool_funcs = [
        task_create, task_list, task_update, task_delete,
        event_create, event_list, event_update, event_delete,
        reminder_set,
    ]
    descriptions = {
        "task_create": "할 일을 생성합니다",
        "task_list": "할 일 목록을 조회합니다",
        "task_update": "할 일을 수정합니다",
        "task_delete": "할 일을 삭제합니다",
        "event_create": "일정을 생성합니다",
        "event_list": "일정 목록을 조회합니다",
        "event_update": "일정을 수정합니다",
        "event_delete": "일정을 삭제합니다",
        "reminder_set": "리마인더를 설정합니다",
    }

    for func in tool_funcs:
        # Bind registry and user_id so they're not exposed to LLM
        bound = partial(func, registry=adapter_registry, user_id=user_id)
        bound.__name__ = func.__name__
        bound.__doc__ = func.__doc__

        # Apply @tool decorator to the bound function
        decorated = tool(description=descriptions.get(func.__name__, func.__doc__ or ""))(bound)
        tool_registry.register(decorated)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_personal_tools.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/personal/tools.py tests/test_personal_tools.py
git commit -m "feat(personal): add LLM tools for task/event/reminder management"
```

---

## Chunk 3: ContextProvider + Profiler + Scheduler + Integration

### Task 8: ContextProvider Plugin Pattern

**Files:**
- Modify: `src/breadmind/memory/context_builder.py`
- Create: `src/breadmind/personal/context_provider.py`
- Test: `tests/test_context_provider.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_context_provider.py
"""Tests for ContextProvider plugin pattern and PersonalContextProvider."""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
import pytest


def test_context_builder_accepts_providers():
    """ContextBuilder should accept and call registered ContextProviders."""
    from breadmind.memory.context_builder import ContextBuilder

    cb = ContextBuilder(working_memory=MagicMock())
    # Should have register_provider method
    assert hasattr(cb, "register_provider")


@pytest.mark.asyncio
async def test_personal_context_provider_schedule_intent():
    from breadmind.personal.context_provider import PersonalContextProvider
    from breadmind.personal.adapters.base import AdapterRegistry
    from breadmind.core.intent import IntentCategory

    registry = AdapterRegistry()

    task_adapter = AsyncMock()
    task_adapter.domain = "task"
    task_adapter.source = "builtin"
    task_adapter.list_items = AsyncMock(return_value=[])
    registry.register(task_adapter)

    event_adapter = AsyncMock()
    event_adapter.domain = "event"
    event_adapter.source = "builtin"
    event_adapter.list_items = AsyncMock(return_value=[])
    registry.register(event_adapter)

    provider = PersonalContextProvider(registry)

    # Mock intent with SCHEDULE category
    intent = MagicMock()
    intent.category = IntentCategory.SCHEDULE

    messages = await provider.get_context("session1", "내일 회의", intent)
    # Should return context messages (possibly empty if no events/tasks)
    assert isinstance(messages, list)
    # Both adapters should be queried
    event_adapter.list_items.assert_called_once()
    task_adapter.list_items.assert_called_once()


@pytest.mark.asyncio
async def test_personal_context_provider_chat_intent_noop():
    from breadmind.personal.context_provider import PersonalContextProvider
    from breadmind.personal.adapters.base import AdapterRegistry
    from breadmind.core.intent import IntentCategory

    registry = AdapterRegistry()
    provider = PersonalContextProvider(registry)

    intent = MagicMock()
    intent.category = IntentCategory.CHAT

    messages = await provider.get_context("session1", "안녕하세요", intent)
    assert messages == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_context_provider.py -v`
Expected: FAIL

- [ ] **Step 3: Add ContextProvider interface to context_builder.py**

Read `src/breadmind/memory/context_builder.py` first. Then add:

1. At top of file, add ABC import and ContextProvider interface:
```python
from abc import ABC, abstractmethod

class ContextProvider(ABC):
    """Plugin interface for injecting domain-specific context."""

    @abstractmethod
    async def get_context(self, session_id: str, message: str, intent: Any) -> list:
        """Return LLMMessage list based on current intent."""
```

2. In `ContextBuilder.__init__()`, add:
```python
    self._context_providers: list[ContextProvider] = []
```

3. Add method:
```python
    def register_provider(self, provider: ContextProvider) -> None:
        self._context_providers.append(provider)
```

4. In `build_context()`, after skill matching section and before conversation history, add:
```python
    # Context providers (domain-specific context injection)
    for provider in self._context_providers:
        try:
            extra = await asyncio.wait_for(
                provider.get_context(session_id, current_message, intent),
                timeout=5,
            )
            messages.extend(extra)
        except Exception:
            pass  # Don't break context building if a provider fails
```

- [ ] **Step 4: Implement PersonalContextProvider**

```python
# src/breadmind/personal/context_provider.py
"""PersonalContextProvider — injects upcoming events and pending tasks into LLM context.

Registered as a ContextProvider plugin in ContextBuilder. Only activates for
SCHEDULE and TASK intents to keep token usage efficient.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from breadmind.memory.context_builder import ContextProvider

if TYPE_CHECKING:
    from breadmind.personal.adapters.base import AdapterRegistry


class PersonalContextProvider(ContextProvider):

    def __init__(self, adapter_registry: AdapterRegistry, default_user_id: str = "default") -> None:
        self._registry = adapter_registry
        self._default_user_id = default_user_id

    async def get_context(self, session_id: str, message: str, intent: Any) -> list:
        from breadmind.core.intent import IntentCategory

        category = getattr(intent, "category", None)
        if category not in (IntentCategory.SCHEDULE, IntentCategory.TASK):
            return []

        now = datetime.now(timezone.utc)
        context_parts: list[str] = []
        # Resolve user_id from session or use default.
        # Working memory sessions store user info; fall back to default_user_id.
        user_id = self._default_user_id

        # Upcoming events (next 48 hours)
        try:
            event_adapter = self._registry.get_adapter("event", "builtin")
            events = await event_adapter.list_items(
                filters={"user_id": user_id, "start_after": now, "start_before": now + timedelta(hours=48)},
                limit=10,
            )
            if events:
                event_lines = [f"  - {e.title} ({e.start_at.strftime('%m/%d %H:%M')})" for e in events]
                context_parts.append("Upcoming events (48h):\n" + "\n".join(event_lines))
        except KeyError:
            pass  # No event adapter registered

        # Pending tasks due soon (next 48 hours)
        try:
            task_adapter = self._registry.get_adapter("task", "builtin")
            tasks = await task_adapter.list_items(
                filters={"user_id": user_id, "status": "pending", "due_before": now + timedelta(hours=48)},
                limit=10,
            )
            if tasks:
                task_lines = [f"  - {t.title} (due: {t.due_at.strftime('%m/%d %H:%M') if t.due_at else 'none'})" for t in tasks]
                context_parts.append("Pending tasks (due within 48h):\n" + "\n".join(task_lines))
        except KeyError:
            pass  # No task adapter registered

        if not context_parts:
            return []

        # Return as a system message (same pattern as ContextBuilder)
        from breadmind.llm.base import LLMMessage

        return [LLMMessage(
            role="system",
            content="## Personal Context\n" + "\n\n".join(context_parts),
        )]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_context_provider.py -v`
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/breadmind/memory/context_builder.py src/breadmind/personal/context_provider.py tests/test_context_provider.py
git commit -m "feat: add ContextProvider plugin pattern and PersonalContextProvider"
```

---

### Task 9: UserProfiler Extension

**Files:**
- Modify: `src/breadmind/memory/profiler.py`
- Test: `tests/test_profiler_extension.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_profiler_extension.py
"""Tests for UserProfiler role/domain extension."""
import pytest


def test_profiler_has_role_field():
    from breadmind.memory.profiler import UserProfiler

    profiler = UserProfiler()
    assert hasattr(profiler, "get_role")


def test_default_role_is_auto():
    from breadmind.memory.profiler import UserProfiler

    profiler = UserProfiler()
    assert profiler.get_role("new_user") == "auto"


def test_set_and_get_role():
    from breadmind.memory.profiler import UserProfiler

    profiler = UserProfiler()
    profiler.set_role("alice", "developer")
    assert profiler.get_role("alice") == "developer"


def test_record_intent_and_determine_role():
    from breadmind.memory.profiler import UserProfiler

    profiler = UserProfiler()
    # Simulate 10 interactions with mostly EXECUTE/DIAGNOSE
    for _ in range(6):
        profiler.record_intent("bob", "execute")
    for _ in range(4):
        profiler.record_intent("bob", "chat")

    role = profiler.determine_role("bob")
    assert role == "developer"


def test_determine_role_general():
    from breadmind.memory.profiler import UserProfiler

    profiler = UserProfiler()
    for _ in range(7):
        profiler.record_intent("carol", "schedule")
    for _ in range(3):
        profiler.record_intent("carol", "task")

    role = profiler.determine_role("carol")
    assert role == "general"


def test_get_exposed_domains_developer():
    from breadmind.memory.profiler import UserProfiler

    profiler = UserProfiler()
    profiler.set_role("alice", "developer")
    domains = profiler.get_exposed_domains("alice")
    assert "infra" in domains
    assert "tasks" in domains


def test_get_exposed_domains_general():
    from breadmind.memory.profiler import UserProfiler

    profiler = UserProfiler()
    profiler.set_role("bob", "general")
    domains = profiler.get_exposed_domains("bob")
    assert "infra" not in domains
    assert "tasks" in domains
    assert "calendar" in domains
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_profiler_extension.py -v`
Expected: FAIL

- [ ] **Step 3: Extend UserProfiler**

Read `src/breadmind/memory/profiler.py`. Then add these fields/methods:

```python
# In __init__:
    self._roles: dict[str, str] = {}  # user -> "developer" | "general" | "auto"
    self._intent_history: dict[str, dict[str, int]] = {}  # user -> {category: count}

# New methods:
    def get_role(self, user: str) -> str:
        return self._roles.get(user, "auto")

    def set_role(self, user: str, role: str) -> None:
        self._roles[user] = role

    def record_intent(self, user: str, category: str) -> None:
        if user not in self._intent_history:
            self._intent_history[user] = {}
        hist = self._intent_history[user]
        hist[category] = hist.get(category, 0) + 1

    def determine_role(self, user: str) -> str:
        """Auto-determine role based on intent history."""
        hist = self._intent_history.get(user, {})
        total = sum(hist.values())
        if total < 10:
            return "auto"

        dev_categories = {"execute", "diagnose", "configure", "query"}
        general_categories = {"schedule", "task", "chat", "contact", "search_files"}

        dev_count = sum(hist.get(c, 0) for c in dev_categories)
        general_count = sum(hist.get(c, 0) for c in general_categories)

        if dev_count / total > 0.4:
            return "developer"
        if general_count / total > 0.6:
            return "general"
        return "developer"  # default: more capabilities

    def get_exposed_domains(self, user: str) -> list[str]:
        role = self.get_role(user)
        base = ["tasks", "calendar", "contacts", "files", "chat"]
        if role in ("developer", "auto"):
            return base + ["infra", "monitoring", "network"]
        return base
```

Also extend `flush_to_db()` and `load_from_db()` to persist `_roles` and `_intent_history`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_profiler_extension.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/memory/profiler.py tests/test_profiler_extension.py
git commit -m "feat(profiler): add role management, intent tracking, and domain exposure"
```

---

### Task 10: PersonalScheduler

**Files:**
- Create: `src/breadmind/personal/proactive.py`
- Test: `tests/test_personal_scheduler.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_personal_scheduler.py
"""Tests for PersonalScheduler (reminders and deadline warnings)."""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.fixture
def mock_deps():
    from breadmind.personal.adapters.base import AdapterRegistry

    registry = AdapterRegistry()

    event_adapter = AsyncMock()
    event_adapter.domain = "event"
    event_adapter.source = "builtin"
    event_adapter.list_items = AsyncMock(return_value=[])
    registry.register(event_adapter)

    task_adapter = AsyncMock()
    task_adapter.domain = "task"
    task_adapter.source = "builtin"
    task_adapter.list_items = AsyncMock(return_value=[])
    registry.register(task_adapter)

    router = AsyncMock()
    router.broadcast_notification = AsyncMock()

    return registry, router, event_adapter, task_adapter


@pytest.mark.asyncio
async def test_check_reminders_sends_notification(mock_deps):
    from breadmind.personal.proactive import PersonalScheduler
    from breadmind.personal.models import Event

    registry, router, event_adapter, _ = mock_deps
    now = datetime.now(timezone.utc)

    # Event starting in 10 minutes with 15-minute reminder
    upcoming_event = Event(
        id="e1", title="Meeting", start_at=now + timedelta(minutes=10),
        end_at=now + timedelta(minutes=70), reminder_minutes=[15],
    )
    event_adapter.list_items.return_value = [upcoming_event]

    scheduler = PersonalScheduler(registry, router)
    await scheduler._check_reminders()

    router.broadcast_notification.assert_called_once()
    call_args = router.broadcast_notification.call_args[0][0]
    assert "Meeting" in call_args


@pytest.mark.asyncio
async def test_check_reminders_no_event(mock_deps):
    from breadmind.personal.proactive import PersonalScheduler

    registry, router, _, _ = mock_deps
    scheduler = PersonalScheduler(registry, router)
    await scheduler._check_reminders()
    router.broadcast_notification.assert_not_called()


@pytest.mark.asyncio
async def test_check_deadlines_sends_warning(mock_deps):
    from breadmind.personal.proactive import PersonalScheduler
    from breadmind.personal.models import Task

    registry, router, _, task_adapter = mock_deps
    now = datetime.now(timezone.utc)

    overdue_task = Task(
        id="t1", title="Submit report", due_at=now + timedelta(hours=6),
        status="pending",
    )
    task_adapter.list_items.return_value = [overdue_task]

    scheduler = PersonalScheduler(registry, router)
    await scheduler._check_deadlines()

    router.broadcast_notification.assert_called_once()
    call_args = router.broadcast_notification.call_args[0][0]
    assert "Submit report" in call_args


@pytest.mark.asyncio
async def test_check_deadlines_no_tasks(mock_deps):
    from breadmind.personal.proactive import PersonalScheduler

    registry, router, _, _ = mock_deps
    scheduler = PersonalScheduler(registry, router)
    await scheduler._check_deadlines()
    router.broadcast_notification.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_personal_scheduler.py -v`
Expected: FAIL

- [ ] **Step 3: Implement PersonalScheduler**

```python
# src/breadmind/personal/proactive.py
"""PersonalScheduler — proactive reminders and deadline warnings.

Runs as a background loop, checking for upcoming events and due tasks.
Sends notifications through the messenger router.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from breadmind.personal.adapters.base import AdapterRegistry

logger = logging.getLogger(__name__)


class PersonalScheduler:

    def __init__(
        self,
        adapter_registry: AdapterRegistry,
        messenger_router: Any,
        check_interval: int = 60,
        default_user_id: str = "default",
    ) -> None:
        self._registry = adapter_registry
        self._router = messenger_router
        self._check_interval = check_interval
        self._default_user_id = default_user_id
        self._notified: set[str] = set()  # Prevent duplicate notifications
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background check loop."""
        self._task = asyncio.create_task(self._loop())
        logger.info("PersonalScheduler started (interval=%ds)", self._check_interval)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("PersonalScheduler stopped")

    async def _loop(self) -> None:
        while True:
            try:
                await self._check_reminders()
                await self._check_deadlines()
            except Exception:
                logger.exception("PersonalScheduler check failed")
            await asyncio.sleep(self._check_interval)

    async def _check_reminders(self) -> None:
        """Check for events with reminders due within the next check interval."""
        now = datetime.now(timezone.utc)
        try:
            adapter = self._registry.get_adapter("event", "builtin")
        except KeyError:
            return

        events = await adapter.list_items(
            filters={"user_id": self._default_user_id, "start_after": now, "start_before": now + timedelta(hours=2)},
            limit=20,
        )

        for event in events:
            for minutes in event.reminder_minutes:
                diff_minutes = (event.start_at - now).total_seconds() / 60
                notify_key = f"reminder:{event.id}:{minutes}"
                if 0 <= diff_minutes <= minutes and notify_key not in self._notified:
                    msg = f"📅 {int(diff_minutes)}분 후: {event.title}"
                    if event.location:
                        msg += f" @ {event.location}"
                    await self._router.broadcast_notification(msg)
                    self._notified.add(notify_key)

    async def _check_deadlines(self) -> None:
        """Check for tasks with deadlines within 24 hours."""
        now = datetime.now(timezone.utc)
        try:
            adapter = self._registry.get_adapter("task", "builtin")
        except KeyError:
            return

        tasks = await adapter.list_items(
            filters={"user_id": self._default_user_id, "status": "pending", "due_before": now + timedelta(hours=24)},
            limit=20,
        )

        for task in tasks:
            notify_key = f"deadline:{task.id}"
            if notify_key not in self._notified:
                hours_left = (task.due_at - now).total_seconds() / 3600 if task.due_at else 0
                msg = f"⚠️ 마감 임박: {task.title} ({int(hours_left)}시간 남음)"
                await self._router.broadcast_notification(msg)
                self._notified.add(notify_key)

    def clear_notifications(self) -> None:
        """Clear notification history (called periodically or on new day)."""
        self._notified.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_personal_scheduler.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/personal/proactive.py tests/test_personal_scheduler.py
git commit -m "feat(personal): add PersonalScheduler for reminders and deadline warnings"
```

---

### Task 11: Tool Registration + Bootstrap Integration

**Files:**
- Modify: `src/breadmind/tools/builtin.py`
- Modify: `src/breadmind/core/bootstrap.py`

- [ ] **Step 1: Read current builtin.py and bootstrap.py**

Read both files to understand the exact registration patterns and DI initialization order.

- [ ] **Step 2: Add personal tools via register_personal_tools (NOT directly to builtin.py)**

Personal tools need `AdapterRegistry` and `user_id` injected via `functools.partial`.
Do NOT add them to `register_builtin_tools()`. Instead, call `register_personal_tools()` from bootstrap.

- [ ] **Step 3: Add AdapterRegistry, personal tools, and PersonalScheduler to bootstrap.py**

In `init_memory()` (Phase 3 of bootstrap), after ContextBuilder creation, add:

```python
    # Personal assistant adapter registry
    from breadmind.personal.adapters.base import AdapterRegistry
    from breadmind.personal.adapters.builtin_task import BuiltinTaskAdapter
    from breadmind.personal.adapters.builtin_event import BuiltinEventAdapter
    from breadmind.personal.context_provider import PersonalContextProvider
    from breadmind.personal.tools import register_personal_tools

    adapter_registry = AdapterRegistry()
    if db:
        adapter_registry.register(BuiltinTaskAdapter(db))
        adapter_registry.register(BuiltinEventAdapter(db))

    # Register personal tools with DI (binds registry + user_id via partial)
    register_personal_tools(registry, adapter_registry, user_id="default")

    # Register personal context provider
    if context_builder:
        context_builder.register_provider(PersonalContextProvider(adapter_registry))
```

Add `adapter_registry` to `AppComponents` dataclass.

In `init_agent()` or after messenger init, add PersonalScheduler:

```python
    # Personal scheduler (after messenger router is available)
    from breadmind.personal.proactive import PersonalScheduler

    if adapter_registry and messenger_router:
        personal_scheduler = PersonalScheduler(adapter_registry, messenger_router)
        await personal_scheduler.start()
```

Add `personal_scheduler` to `AppComponents`.

- [ ] **Step 4: Update agent's ALWAYS_INCLUDE tools**

In `src/breadmind/core/agent.py`, `_filter_relevant_tools()` method, add to `ALWAYS_INCLUDE`:

```python
    "task_create", "task_list", "event_create", "event_list", "reminder_set",
```

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/builtin.py src/breadmind/core/bootstrap.py src/breadmind/core/agent.py
git commit -m "feat: integrate personal assistant into bootstrap, tool registry, and agent"
```

---

### Task 12: Intent Recording in Agent Loop

**Files:**
- Modify: `src/breadmind/core/agent.py`

- [ ] **Step 1: Add intent recording to handle_message**

In `handle_message()`, after intent classification and before context building, add:

```python
    # Record intent for role auto-determination
    if self._profiler:
        self._profiler.record_intent(user, intent.category.value)
```

This enables the UserProfiler to track intent patterns and auto-determine user roles.

- [ ] **Step 2: Commit**

```bash
git add src/breadmind/core/agent.py
git commit -m "feat(agent): record intent history for adaptive user profiling"
```

---

### Task 13: Final Integration Test

- [ ] **Step 1: Run all tests**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests PASS (existing + new)

- [ ] **Step 2: Verify import chain**

```python
# Quick import smoke test
python -c "
from breadmind.personal.models import Task, Event, Contact, File, Message
from breadmind.personal.adapters.base import ServiceAdapter, AdapterRegistry, SyncResult
from breadmind.personal.adapters.builtin_task import BuiltinTaskAdapter
from breadmind.personal.adapters.builtin_event import BuiltinEventAdapter
from breadmind.personal.tools import task_create, event_create, reminder_set
from breadmind.personal.context_provider import PersonalContextProvider
from breadmind.personal.proactive import PersonalScheduler
from breadmind.core.intent import IntentCategory
print('All imports OK')
print('New categories:', [c for c in IntentCategory if c.value in ('schedule','task','search_files','contact')])
"
```
Expected: `All imports OK` + 4 new categories listed

- [ ] **Step 3: Final commit with all remaining changes**

```bash
git add -A
git commit -m "feat(personal): complete Phase 1 — universal personal assistant foundation"
```
