# BreadMind Self-Expansion System Design

**Date:** 2026-03-15
**Status:** Approved (rev.3 — all review issues resolved)
**Approach:** Layered self-expansion (approach 1 — hierarchical)

## Overview

BreadMind에 4개의 자기 확장 컴포넌트를 추가하여, 에이전트가 스스로 도구를 발견·설치하고, 역할을 생성하고, 반복 패턴을 skill로 저장하며, 성능을 추적·개선할 수 있도록 한다.

## Architecture

```
PerformanceTracker (기반 데이터 계층)
    ↑
SkillStore (패턴 저장/검색 계층)
    ↑
ToolGapDetector (도구 부족 감지 계층)
    ↑
TeamBuilder (팀 자동 구성 계층)
```

하위 컴포넌트가 상위 컴포넌트에 데이터를 제공한다. TeamBuilder는 PerformanceTracker의 역할별 성공률을 참조하여 팀 구성을 최적화한다.

## Component 1: PerformanceTracker

**File:** `src/breadmind/core/performance.py`

### Responsibility
Swarm 역할 및 Skill의 실행 성과를 실시간 추적하고, 저성과 역할에 대해 프롬프트 개선을 제안한다.

### Data Model

```python
@dataclass
class TaskRecord:
    role: str
    task_description: str
    success: bool
    duration_ms: float
    result_summary: str
    timestamp: datetime

@dataclass
class RoleStats:
    role: str
    total_runs: int = 0
    successes: int = 0
    failures: int = 0
    total_duration_ms: float = 0.0
    recent_records: list[TaskRecord]  # 최근 100건
    feedback_history: list[dict]      # [{rating, comment, timestamp}]

    @property
    def success_rate(self) -> float

    @property
    def avg_duration_ms(self) -> float
```

### Interface

```python
class PerformanceTracker:
    def __init__(self, db: Database | None = None)

    # Recording
    async def record_task_result(role, task_desc, success, duration_ms, result_summary)
    async def record_feedback(role, rating: str, comment: str)

    # Querying
    def get_role_stats(role) -> RoleStats | None
    def get_all_stats() -> dict[str, RoleStats]
    def get_underperforming_roles(threshold: float = 0.5) -> list[RoleStats]
    def get_top_roles(limit: int = 5) -> list[RoleStats]

    # Improvement suggestions
    async def suggest_improvements(role, message_handler) -> str

    # Persistence
    async def flush_to_db()
    async def load_from_db()
```

### Concurrency
- All mutation methods acquire `self._lock: asyncio.Lock` before modifying `_stats`.
- asyncio는 cooperative이므로 Lock은 경량이지만, `asyncio.gather()`로 병렬 실행되는 swarm task들이 동시에 `record_task_result()`를 호출할 수 있어 필요하다.

### Behavior
- SwarmManager calls `record_task_result()` after each task completion.
- In-memory rolling stats: last 100 detailed records per role, aggregates for all time.
- DB flush every 5 minutes via scheduler (key: `performance_stats` in settings).
- `suggest_improvements()` sends failure patterns to LLM for prompt revision suggestions.
- **Trade-off:** settings 테이블에 JSON blob으로 저장하는 것은 초기 구현용. 역할 수가 50+를 넘으면 dedicated 테이블 마이그레이션을 고려한다.

## Component 2: SkillStore

**File:** `src/breadmind/core/skill_store.py`

### Responsibility
재사용 가능한 워크플로/프롬프트 템플릿을 skill로 저장·검색·실행한다. 반복 패턴을 자동 감지하여 skill 생성을 제안한다.

### Data Model

```python
@dataclass
class Skill:
    name: str
    description: str
    prompt_template: str          # 실행 시 사용할 프롬프트 템플릿
    steps: list[str]              # 워크플로 단계 설명
    trigger_keywords: list[str]   # 자동 매칭용 키워드
    usage_count: int = 0
    success_count: int = 0
    created_at: datetime
    updated_at: datetime
    source: str = "auto"          # auto | manual
```

### Interface

```python
class SkillStore:
    def __init__(self, db: Database | None = None, tracker: PerformanceTracker | None = None)

    # CRUD
    async def add_skill(name, description, prompt_template, steps, trigger_keywords, source) -> Skill
    async def update_skill(name, **kwargs)
    async def remove_skill(name) -> bool
    async def get_skill(name) -> Skill | None
    async def list_skills() -> list[Skill]

    # Search & match
    async def find_matching_skills(query: str, limit: int = 3) -> list[Skill]

    # Pattern detection
    async def detect_patterns(recent_tasks: list[dict], message_handler) -> list[dict]
    #   Returns: [{name, description, prompt_template, trigger_keywords}]

    # Execution tracking
    async def record_usage(name, success: bool)

    # Persistence
    async def flush_to_db()
    async def load_from_db()
```

### Concurrency
- PerformanceTracker와 동일하게 `self._lock: asyncio.Lock` 사용.

### Pattern Detection Trigger
- `detect_patterns()`는 SwarmManager가 swarm 완료 후 호출한다.
- 조건: 최근 10건의 완료된 swarm task가 축적될 때마다 1회 실행.
- SwarmManager가 완료 카운터를 유지하고 threshold 도달 시 `detect_patterns()`를 호출, 결과를 사용자에게 제안 메시지로 전달한다.

### Behavior
- Skills are stored in memory with DB persistence (key: `skill_store` in settings).
- `detect_patterns()`: receives recent task history, asks LLM to identify recurring patterns, returns skill proposals.
- `find_matching_skills()`: keyword-based matching against trigger_keywords + description.
- SwarmManager can inject matching skills into task prompts as context.
- A meta tool `skill_manage` is registered for chat-based CRUD.

## Component 3: ToolGapDetector

**File:** `src/breadmind/core/tool_gap.py`

### Responsibility
Agent의 tool 실행 실패 중 "unknown tool" 패턴을 인터셉트하여, 자동으로 MCP 레지스트리를 검색하고 사용자 승인 후 설치하는 체인을 실행한다.

### Interface

```python
class ToolGapDetector:
    def __init__(self, tool_registry: ToolRegistry, mcp_manager: MCPClientManager,
                 search_engine: RegistrySearchEngine, db: Database | None = None)

    async def check_and_resolve(tool_name: str, arguments: dict, user: str, channel: str) -> ToolGapResult
    #   Returns: ToolGapResult(resolved, message, suggestions)

    async def search_for_capability(description: str) -> list[MCPSuggestion]
    #   Searches registries for tools matching a capability description

    def get_pending_installs(self) -> list[dict]
    #   Returns pending MCP install suggestions awaiting user approval

    async def approve_install(suggestion_id: str) -> str
    #   Executes approved MCP installation

    async def deny_install(suggestion_id: str)
```

### Data Model

```python
@dataclass
class ToolGapResult:
    resolved: bool                    # True if tool was found and installed
    message: str                      # Human-readable status
    suggestions: list[MCPSuggestion]  # Candidate MCP servers

@dataclass
class MCPSuggestion:
    id: str
    tool_name: str           # The missing tool name
    mcp_name: str            # MCP server name from registry
    mcp_description: str
    install_command: str
    source: str              # clawhub | mcp_registry
    status: str = "pending"  # pending | approved | denied | installed
```

### Integration with CoreAgent

**Critical: ToolRegistry 변경 필요**

`ToolRegistry.execute()`가 현재 `ToolResult(success=False, output="Tool not found: ...")` 문자열을 반환한다. 문자열 매칭은 취약하므로, `ToolResult`에 `not_found: bool = False` 필드를 추가하고, `execute()`에서 도구를 찾지 못했을 때 `ToolResult(success=False, output=..., not_found=True)`를 반환하도록 수정한다.

CoreAgent는 `result.not_found`를 확인하여 ToolGapDetector를 호출한다:

1. `_execute_one()`에서 `result.not_found == True` 감지.
2. `ToolGapDetector.check_and_resolve(tool_name, args, user, channel)` 호출.
3. If suggestions found, 도구 결과 메시지에 제안 정보를 포함:
   `"Tool '{name}' not found. Found MCP servers that may provide it: [suggestions]. Approval required to install."`
4. LLM sees suggestions and can inform the user.
5. User approval triggers `approve_install()` → MCP server starts → tools registered → retry.

### Reuse of Existing Meta Tools

ToolGapDetector는 `mcp_search`/`mcp_install` 로직을 재구현하지 않는다. 대신 `RegistrySearchEngine.search()`를 직접 호출하여 검색하고, 설치 승인 시 `MCPClientManager.start_stdio_server()`를 호출한다. 이는 `meta.py`의 `mcp_install` 도구가 내부적으로 사용하는 것과 동일한 하위 API이다.

### Error Handling
- `search_for_capability()` 실패 시 (네트워크 오류 등) `ToolGapResult(resolved=False, message="Registry search failed", suggestions=[])` 반환. 에러를 상위로 전파하지 않는다.
- `MCPSuggestion.id`는 `uuid.uuid4()[:8]`로 생성 (CoreAgent._pending_approvals 패턴과 동일).

### Behavior
- Caches recent searches to avoid duplicate queries (TTL: 10 minutes).
- Tracks gap history for pattern analysis (which tools are frequently missing).
- Max 10 pending suggestions (FIFO eviction).

## Component 4: TeamBuilder

**File:** `src/breadmind/core/team_builder.py`

### Responsibility
Swarm 실행 전에 목표를 분석하여, 기존 역할을 평가하고, 부족한 역할을 자동 생성하며, 최적의 팀을 구성하여 SwarmCoordinator에 전달한다.

### Interface

```python
class TeamBuilder:
    def __init__(self, swarm_manager: SwarmManager, tracker: PerformanceTracker,
                 skill_store: SkillStore, message_handler=None)

    async def build_team(goal: str) -> TeamPlan
    #   Analyzes goal, evaluates existing roles, creates missing ones, returns optimal team

    async def evaluate_existing_roles(goal: str) -> list[RoleAssessment]
    #   Scores each existing role's relevance to the goal

    async def create_role_for_gap(gap_description: str) -> SwarmMember
    #   Uses LLM to generate a new specialized role
```

### Data Model

```python
@dataclass
class RoleAssessment:
    role: str
    relevance_score: float    # 0.0 ~ 1.0
    success_rate: float       # From PerformanceTracker
    recommendation: str       # "use" | "skip" | "improve"

@dataclass
class TeamPlan:
    goal: str
    selected_roles: list[str]
    created_roles: list[str]       # Newly auto-generated roles
    skill_injections: dict[str, list[str]]  # role -> [skill prompts to inject]
    reasoning: str                 # LLM's reasoning for team composition
```

### Integration with SwarmManager

In `SwarmManager._execute_swarm()`, before calling `coordinator.decompose()`:

1. `TeamBuilder.build_team(goal)` is called.
2. TeamBuilder asks LLM: "Given this goal and these available roles (with their success rates), which roles are needed? Are any missing?"
3. If gaps identified, `create_role_for_gap()` generates new SwarmMember with system_prompt.
4. New roles are registered via `swarm_manager.add_role()` and persisted.
5. Matching skills from SkillStore are injected into the team plan.
6. SwarmCoordinator.decompose() now has access to the expanded role set.

### Role Lifecycle Management
- TeamBuilder가 생성하는 역할은 `source: "auto"` 마커를 갖는다 (SwarmMember에 `source` 필드 추가).
- 자동 생성된 역할은 30일간 미사용 시 또는 성공률 < 20% 시 삭제 후보로 표시된다.
- PerformanceTracker의 flush 시점에 삭제 후보를 확인하고, 조건 충족 시 `swarm_manager.remove_role()`로 정리한다.

### swarm_role 도구와의 관계
- 기존 `swarm_role` 도구는 사용자가 수동으로 역할을 관리하는 인터페이스이다.
- TeamBuilder는 `SwarmManager.add_role()`을 직접 호출하여 역할을 생성한다 (swarm_role 도구를 거치지 않음).
- 수동 생성 역할(`source: "manual"`)은 자동 정리 대상에서 제외된다.

### SwarmCoordinator.decompose() 수정
- 현재 `decompose()`가 `DEFAULT_ROLES.keys()`를 하드코딩으로 LLM에 전달한다.
- `SwarmManager._roles.keys()`를 사용하도록 수정하여, TeamBuilder가 생성한 역할도 decompose에서 참조 가능하게 한다.
- SwarmCoordinator에 `available_roles` 파라미터를 추가하고, SwarmManager가 전달한다.
- **`_parse_tasks()` 역시 `available_roles`를 받아** 역할 유효성 검증에 사용한다. 현재 `DEFAULT_ROLES`로 검증하면 auto-created 역할이 `"general"`로 대체되는 버그 발생.

### SwarmMember.source 필드 추가
- `SwarmMember`에 `source: str = "manual"` 필드를 추가한다.
- `SwarmManager.add_role()`에 `source: str = "manual"` 파라미터를 추가한다.
- DB에서 기존 역할 로드 시 `source` 필드가 없으면 `"manual"`로 기본값 설정 (기존 데이터 안전성 보장).

### Behavior
- Uses PerformanceTracker data to prefer high-performing roles.
- Avoids creating duplicate roles (similarity check against existing roles).
- Max 3 new roles per team build (to prevent unbounded growth).
- LLM prompt includes role stats summary for informed decision-making.
- TeamBuilder LLM 호출에 cooldown 적용: 동일 목표 패턴에 대해 5분 내 재호출 방지 (캐시).

## Integration Points Summary

### main.py initialization order
1. `PerformanceTracker(db)` → `await load_from_db()`
2. `SkillStore(db, tracker)` → `await load_from_db()`
3. `ToolGapDetector(registry, mcp_manager, search_engine, db)`
4. `TeamBuilder(swarm_manager, tracker, skill_store, message_handler)`
5. Inject ToolGapDetector into CoreAgent
6. Inject TeamBuilder into SwarmManager

### CoreAgent changes
- Add `_tool_gap_detector` field
- In tool execution loop: intercept "unknown tool" errors → delegate to ToolGapDetector

### SwarmManager changes
- Add `_team_builder` and `_tracker` fields
- In `_execute_swarm()`: call TeamBuilder before decompose, call PerformanceTracker after each task

### New meta tools
- `skill_manage(action, name, ...)` — CRUD for skills via chat
- `performance_report(role?)` — View performance stats via chat

### Web API endpoints
- `GET /api/skills` — List skills
- `POST /api/skills` — Create skill
- `PUT /api/skills/{name}` — Update skill
- `DELETE /api/skills/{name}` — Delete skill
- `GET /api/performance` — View performance stats
- `GET /api/performance/{role}` — Role-specific stats

## File Size Estimates
- `core/performance.py`: ~250 lines
- `core/skill_store.py`: ~300 lines
- `core/tool_gap.py`: ~250 lines
- `core/team_builder.py`: ~200 lines
- Changes to `core/agent.py`: ~30 lines added
- Changes to `core/swarm.py`: ~20 lines added
- Changes to `main.py`: ~40 lines added
- New meta tools in `tools/meta.py`: ~80 lines added
- Web API additions in `web/app.py`: ~80 lines added
- **Total: ~1,250 lines new code**
