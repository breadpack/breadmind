# Background Task System Design

## Summary

BreadMind에서 장시간 복잡 작업(서버 점검, 보안 스캔 등)과 지속적 모니터링 작업을 백그라운드에서 실행하고, 서버 재시작 후에도 작업 상태를 복구/재개할 수 있는 시스템.

**Goal:** Celery + Redis 기반으로 백그라운드 작업 큐를 구축하여, 장시간 작업의 영속적 실행/일시정지/재개/취소를 지원하고, 웹 UI와 메신저 양쪽으로 진행 상황 및 결과를 전달한다.

## 전제 조건

- **PostgreSQL 필수**: 백그라운드 작업은 DB 영속성이 필요하므로, FileSettingsStore 모드에서는 비활성화된다.
- **Redis 필수**: Celery 브로커 + 결과 백엔드 + Pub/Sub 알림.

## 전체 아키텍처

```
사용자 → "서버 10대 보안 점검해줘" (웹 UI / 메신저)
    ↓
CoreAgent.handle_message()
    → LLM이 run_background 도구 호출 (장시간 작업 판단)
    → Celery 태스크 발행 (Redis 브로커)
    → 즉시 응답: "백그라운드 작업 #task-id 시작됨"
    ↓
Celery Worker (별도 프로세스, gevent pool)
    → worker_bootstrap: DB, ToolRegistry, SafetyGuard, LLM 초기화
    → asyncio.run() 래퍼로 async 도구 호출
    → 단계별 실행: LLM이 각 step을 도구 호출 계획으로 변환
    → 진행 상황 DB 업데이트 + Redis Pub/Sub 발행
    → 완료 시 결과 DB 저장
    ↓
알림 전달 (2가지 경로)
    → WebSocket: Redis 구독 리스너 → 연결된 클라이언트에 푸시
    → 메신저: MessageRouter를 통해 마일스톤 알림 전송

재접속 시
    → GET /api/bg-jobs — DB에서 모든 작업 상태 조회
    → WebSocket 연결 시 진행 중 작업의 실시간 업데이트 구독
```

## 네이밍 규칙

기존 Personal Assistant의 `tasks` 테이블/API와 충돌을 피하기 위해:
- DB 테이블: `bg_jobs`
- API 경로: `/api/bg-jobs/...`
- 빌트인 도구: `run_background` (기존 `tasks` 관련 도구와 혼동 방지)
- 클래스: `BackgroundJobManager`

## 작업 유형

### 1. 단일 복잡 작업 (single)
- 예: "서버 10대 보안 점검하고 보고서 만들어"
- 유한한 단계, 완료 조건 명확
- 완료 시 결과 보고서 생성

### 2. 지속 모니터링 작업 (monitor)
- 예: "이 서버 모니터링하다가 문제 생기면 자동 대응해"
- 이벤트 기반, 주기적 체크 루프
- 사용자가 취소할 때까지 실행
- 이상 감지 시 알림 + 자동 대응
- **최대 동시 모니터 작업: 10개** (리소스 보호)

## 작업 상태 모델

### 상태 흐름

```
pending → running → completed
                  → failed
         → paused (revoke + 상태 DB 저장) → running (재발행)
         → cancelled (revoke + 정리)
```

### 일시정지/재개 메커니즘

Worker 슬롯을 점유하지 않는 방식:
1. **일시정지**: Celery `revoke()` 호출 + DB에 `status=paused`, `progress.last_completed_step` 저장
2. **재개**: DB에서 마지막 완료 단계 읽기 → 새 Celery 태스크 발행 (해당 단계부터 재개)
3. Worker가 각 단계 시작 전 DB에서 status 체크 → `cancelled`면 정리 후 종료

### DB 테이블: bg_jobs

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID | PK |
| celery_task_id | VARCHAR | 현재 Celery 태스크 ID (재발행 시 변경됨) |
| title | VARCHAR(200) | 사용자 표시용 제목 |
| description | TEXT | 원래 요청 메시지 |
| status | VARCHAR(20) | pending/running/paused/completed/failed/cancelled |
| job_type | VARCHAR(20) | single / monitor |
| user | VARCHAR | 요청 사용자 |
| channel | VARCHAR | 원래 채널 |
| platform | VARCHAR(20) | web/slack/discord 등 |
| progress | JSONB | {last_completed_step, total_steps, message, percentage} |
| result | TEXT | 최종 결과 (최대 100KB, 초과 시 truncate + 전체 결과 파일 경로) |
| error | TEXT | 에러 메시지 |
| execution_plan | JSONB | LLM이 생성한 구체적 실행 계획 [{step, tool, args}, ...] |
| created_at | TIMESTAMP | 생성 시각 |
| updated_at | TIMESTAMP | 마지막 상태 변경 |
| started_at | TIMESTAMP | 실행 시작 |
| completed_at | TIMESTAMP | 완료 시각 |
| metadata | JSONB | 추가 컨텍스트 (대상 서버 목록, monitor_config 등) |

전용 테이블. `database.py`에 bg_jobs CRUD 메서드 추가.

### 완료 작업 보관 정책

- 완료/실패 작업: 30일 후 자동 삭제 (MemoryGC와 유사한 주기 정리)
- result가 100KB 초과 시: 파일로 저장, DB에는 경로만 기록

## 실행 모델

### 2단계 실행: 계획 → 실행

1. **계획 단계** (LLM 호출 1회): `run_background` 도구 호출 시 LLM이 자연어 steps를 구체적 실행 계획으로 변환

```json
{
  "execution_plan": [
    {"step": 1, "description": "서버 10.0.0.1 포트 스캔", "tool": "network_scan", "args": {"target": "10.0.0.1"}},
    {"step": 2, "description": "SSH 접속", "tool": "router_manage", "args": {"action": "connect", "host": "10.0.0.1"}},
    ...
  ]
}
```

2. **실행 단계** (Worker): 계획된 도구 호출을 순차 실행. 추가 LLM 호출 없음 (비용 절감).
   - 예외: 도구 결과에 따라 동적 판단이 필요한 경우, 해당 step에 `"requires_llm": true` 플래그

### Monitor 작업 실행

```json
{
  "monitor_config": {
    "interval_seconds": 60,
    "check_tool": "shell_exec",
    "check_args": {"command": "ping -c 1 10.0.0.1"},
    "alert_condition": "packet loss > 0",
    "response_tool": "shell_exec",
    "response_args": {"command": "systemctl restart ..."}
  }
}
```

Worker가 주기적으로 check_tool 실행 → 조건 충족 시 response_tool 실행 + 알림.

## 컴포넌트 구조

### 새 파일
- **`src/breadmind/tasks/__init__.py`**
- **`src/breadmind/tasks/celery_app.py`** — Celery 앱 인스턴스, Redis 설정
- **`src/breadmind/tasks/worker.py`** — Celery 태스크 정의 + worker_bootstrap (async 브릿지)
- **`src/breadmind/tasks/manager.py`** — BackgroundJobManager (CRUD, 상태 조회, 일시정지/재개/취소)
- **`src/breadmind/web/routes/bg_jobs.py`** — REST API 엔드포인트

### 수정 파일
- **`src/breadmind/storage/database.py`** — bg_jobs 테이블 생성 및 CRUD 메서드
- **`src/breadmind/tools/builtin.py`** — `run_background` 빌트인 도구 등록
- **`src/breadmind/core/bootstrap.py`** — BackgroundJobManager 초기화, Redis Pub/Sub 리스너
- **`src/breadmind/web/app.py`** — bg_jobs 라우터 등록, Redis 구독 startup task
- **`src/breadmind/web/routes/chat.py`** — WebSocket에서 태스크 진행 상황 브로드캐스트
- **`src/breadmind/config.py`** — Redis URL, TaskConfig

## Celery Worker 구성

### Pool 타입: gevent

```bash
celery -A breadmind.tasks.celery_app worker --pool=gevent --loglevel=info
```

gevent pool을 사용하여 async 도구와의 호환성 확보. Worker 내부에서 `asyncio.run()`으로 async 함수 실행.

### Worker Bootstrap

Worker 프로세스 시작 시 `worker_bootstrap()` 실행:

```python
# breadmind/tasks/worker.py

_registry = None
_db = None
_guard = None

@worker_process_init.connect
def worker_bootstrap(**kwargs):
    """Worker 프로세스 초기화 — bootstrap_all의 경량 버전."""
    global _registry, _db, _guard
    import asyncio
    loop = asyncio.new_event_loop()

    # Phase 1: DB 연결
    _db = loop.run_until_complete(init_db())

    # Phase 2: ToolRegistry + SafetyGuard
    _registry = ToolRegistry()
    register_builtin_tools(_registry)
    _guard = SafetyGuard(load_safety_config())

    # Phase 3: LLM provider (requires_llm step용)
    # ... 필요 시 초기화
```

### Async-to-Sync 브릿지

```python
@celery_app.task(bind=True)
def execute_bg_job(self, job_id: str):
    asyncio.run(_execute_bg_job_async(self, job_id))

async def _execute_bg_job_async(celery_task, job_id: str):
    job = await _db.get_bg_job(job_id)
    plan = job["execution_plan"]

    for step in plan[job["progress"]["last_completed_step"]:]:
        # 상태 체크
        current = await _db.get_bg_job(job_id)
        if current["status"] == "cancelled":
            return
        # 도구 실행
        result = await _registry.execute(step["tool"], step["args"])
        # 진행 상황 업데이트
        await _db.update_bg_job_progress(job_id, step["step"], result)
        # Redis Pub/Sub 알림
        await _publish_progress(job_id, step, result)
```

## API 엔드포인트

### `GET /api/bg-jobs` — 작업 목록 (상태 필터: ?status=running)

### `GET /api/bg-jobs/{job_id}` — 작업 상세

### `POST /api/bg-jobs/{job_id}/pause` — 일시정지

### `POST /api/bg-jobs/{job_id}/resume` — 재개

### `POST /api/bg-jobs/{job_id}/cancel` — 취소

### `DELETE /api/bg-jobs/{job_id}` — 삭제 (completed/failed/cancelled만)

## run_background 빌트인 도구

```json
{
  "name": "run_background",
  "description": "Start a long-running background job. Use for tasks that take more than a few minutes.",
  "parameters": {
    "title": "작업 제목",
    "job_type": "single | monitor",
    "steps": ["step 1 description", "step 2 description"],
    "tools_needed": ["shell_exec", "router_manage"],
    "monitor_config": {"interval_seconds": 60, ...}
  }
}
```

도구 호출 시:
1. LLM이 steps를 구체적 execution_plan으로 변환 (tool + args 바인딩)
2. DB에 bg_job 레코드 생성
3. Celery 태스크 발행
4. `"백그라운드 작업 '{title}' (ID: {job_id}) 시작됨"` 반환

## 알림 전달

### Redis Pub/Sub (Worker → Web Server)

- 채널 이름: `breadmind:bg_job:{job_id}`
- 메시지 형식: `{"type": "progress|completed|failed", "job_id": "...", "data": {...}}`

### Web Server 측 Redis 구독

FastAPI startup 이벤트에서 Redis 구독 리스너를 백그라운드 asyncio task로 시작:

```python
@app.on_event("startup")
async def start_redis_listener():
    asyncio.create_task(redis_bg_job_listener(app))

async def redis_bg_job_listener(app):
    """Redis Pub/Sub → WebSocket 브로드캐스트."""
    pubsub = redis.pubsub()
    await pubsub.psubscribe("breadmind:bg_job:*")
    async for msg in pubsub.listen():
        if msg["type"] == "pmessage":
            await app.state.app_state.broadcast_event(json.loads(msg["data"]))
```

### 메신저 알림

Worker가 주요 마일스톤에서 Redis를 통해 알림 발행 → Web Server의 리스너가 MessageRouter.send_message() 호출.

## 서버 재시작 복구

1. bootstrap 시 DB에서 `status IN ('running', 'pending')` 작업 조회
2. 각 작업의 `celery_task_id`로 Celery inspect 확인
3. 죽어있으면:
   - `progress.last_completed_step` 확인 (= 마지막으로 완전히 완료된 단계)
   - 해당 단계 다음부터 새 Celery 태스크 발행
4. Monitor 작업: 무조건 재발행 (상태 없는 주기적 체크이므로)

### 멱등성 가이드

- 각 step의 `last_completed_step`은 **완전히 완료된** 단계만 기록
- 중단된 step은 처음부터 재실행 (부분 실행 복구 안 함)
- 부작용이 있는 도구(VM 생성 등)는 step 실행 전 이미 완료 여부 체크 권장

## 설정

### 환경변수

- `BREADMIND_REDIS_URL` — Redis 연결 URL (기본: `redis://localhost:6379/0`)

### config.py 추가

```python
@dataclass
class TaskConfig:
    redis_url: str = "redis://localhost:6379/0"
    max_concurrent_monitors: int = 10
    result_max_size_kb: int = 100
    completed_retention_days: int = 30
```

## 보안

- 모든 bg-jobs API는 기존 AuthManager 인증 필수
- 현재 싱글 유저 모드이므로, 인증된 세션이면 모든 작업에 접근 가능
- 향후 멀티유저 지원 시 `user` 필드 기반 소유권 검사 추가
- Worker가 실행하는 도구는 SafetyGuard 통과 필수
- 작업 결과에 포함된 credential은 CredentialVault.sanitize_text() 적용

## 웹 UI

- 새 "Jobs" 탭 또는 기존 모니터링 탭에 작업 목록 표시
- 각 작업: 진행률 바, 상태 배지, 일시정지/재개/취소 버튼
- 완료된 작업의 결과 펼쳐보기
- WebSocket으로 실시간 진행 업데이트
