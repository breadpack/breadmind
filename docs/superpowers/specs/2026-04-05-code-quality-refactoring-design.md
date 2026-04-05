# BreadMind 코드 품질 리팩토링 설계

**날짜**: 2026-04-05
**범위**: Phase 1~3 (데드코드 정리, 하드코딩 해소, 중복 제거, 아키텍처 리팩토링)
**실행 방식**: 병렬 스트림 (Stream 1~5 독립 실행 → Stream 6~8 순차 실행)

---

## 배경

5개 관점(과잉구현, 하드코딩, 중복구현, 미사용 로직, SOLID 원칙)으로 코드 리뷰를 수행한 결과, HIGH 25건, MEDIUM 29건, LOW 21건 이상의 개선 항목이 도출됨. 종합 점수 49/100으로 즉각적인 개선이 필요.

## Phase 1: 기반 정리 (Stream 1~3, 병렬)

### Stream 1: 데드코드 정리

**삭제 대상:**
- `provisioning/strategies/kubernetes.py`, `proxmox.py`, `ssh.py` — TODO stub만 존재
- `tools/search_providers.py` 내 NotImplementedError 클래스 5개 (Exa, Tavily, Firecrawl, SearXNG, 기본값)
- `coding/adapters/codex.py` — 23줄, 미사용 어댑터
- `llm/factory.py` 내 `AuthRotator` 클래스 — 정의만 있고 미사용
- `core/context_engine.py` 내 미구현 추상 메서드(ellipsis만) 정리

**방침:**
- 삭제 전 grep으로 import 참조 확인
- 참조가 있으면 참조도 함께 제거
- `provisioning/strategies/base.py`는 유지 (향후 구현 시 베이스)

### Stream 2: 하드코딩 해소

**새 파일:** `src/breadmind/constants.py`
- LLM: `DEFAULT_MODEL`, `DEFAULT_MAX_TOKENS`, `THINKING_MAX_TOKENS`, `DEFAULT_THINK_BUDGET`
- 네트워크: `DEFAULT_REDIS_URL`, `DEFAULT_OLLAMA_URL`, `DEFAULT_CDP_URL`
- 제한: `TEXT_TRUNCATION_LIMIT`, `SESSION_TIMEOUT_SECONDS`

**config.py 개선:**
- `redis://localhost:6379/0` 3중 중복 → `constants.py`에서 import
- `celery_app.py`, `worker.py`도 동일하게 변경

**모델 가격표:**
- `cost_tracker.py` 내 하드코딩 가격 → `config/model_pricing.yaml`로 이동
- 파일 없으면 fallback으로 기존 하드코딩 값 사용

**LLM 모델명:**
- `claude.py`, `opus_plan.py` 등에서 하드코딩된 모델명 → `constants.py` 상수로 이동
- `max_tokens` 매직넘버(4096, 16384, 10000) → 명명된 상수로 대체

**방침:** 환경변수 fallback 패턴 유지 (`os.environ.get(ENV_KEY, CONSTANT)`)

### Stream 3: 중복 데이터클래스 통합

**단일 소스:** `llm/base.py`의 `ToolCall`, `TokenUsage`, `LLMResponse`를 정본으로 지정
**삭제:** `core/protocols/provider.py` 내 중복 정의 제거
**마이그레이션:** 모든 `from breadmind.core.protocols.provider import ToolCall` → `from breadmind.llm.base import ToolCall`

## Phase 2: 중복 해소 (Stream 4~5, 병렬)

### Stream 4: 메신저 게이트웨이 리팩토링

**기본 클래스 강화:** `messenger/base.py` (또는 기존 MessengerGateway)에 공통 로직 구현
- `__init__()`: 공통 필드 초기화 (token, handler, channel 등)
- `start()`/`stop()`: 공통 라이프사이클 (ImportError 처리 포함)
- `ask_approval()`: UUID 생성 + 승인 메시지 포맷팅 기본 구현
- `_create_incoming_message()`: IncomingMessage 팩토리 메서드
- `_safe_import()`: ImportError 처리 패턴 통합

**9개 게이트웨이 리팩토링:**
- `slack.py`, `discord_gw.py`, `telegram_gw.py`, `whatsapp_gw.py`, `signal_gw.py`, `gmail_gw.py`, `line_gw.py`, `matrix_gw.py`, `teams_gw.py`
- 각 게이트웨이는 플랫폼별 세부사항만 오버라이드
- 공통 `ask_approval()` 사용, 플랫폼별 메시지 포맷만 커스터마이즈

**AutoConnector 리팩토링:**
- `auto_connect/base.py`에 공통 설정 단계 패턴 추출
- 9개 플랫폼별 AutoConnector는 메타데이터(URL, 지시사항)만 정의

### Stream 5: 공통 유틸리티 모듈

**새 파일:** `src/breadmind/utils/`
- `serialization.py`: `SerializableMixin` — `to_dict()`, `from_dict()`, `to_json()`, `from_json()` 기본 구현
- `helpers.py`:
  - `generate_short_id(length=8)` — UUID 단축 생성 (10개+ 파일에서 중복)
  - `cancel_task_safely(task)` — 비동기 작업 취소 패턴 (4개 파일 중복)
  - `safe_import(module_name, package_name)` — ImportError 처리 패턴
- `file_io.py`:
  - `ensure_dir(path)` — mkdir(parents=True, exist_ok=True) 래퍼
  - `read_text_safe(path, encoding="utf-8")` — 일관된 파일 읽기
  - `write_text_safe(path, content, encoding="utf-8")` — 일관된 파일 쓰기

**마이그레이션:** 기존 중복 코드를 유틸리티 모듈 호출로 대체

## Phase 3: 아키텍처 리팩토링 (Stream 6~8, Phase 2 완료 후)

### Stream 6: CoreAgent 책임 분리

**현재 문제:** 694줄, 27개 메서드, 34개 초기화 파라미터, 8개 이상 책임

**분리 계획:**
- `core/conversation_manager.py` 추출:
  - 메시지 히스토리 구성
  - 컨텍스트 enrichment
  - 메시지 summarization
  - Token counting
- `core/tool_coordinator.py` 추출:
  - 도구 필터링
  - Tool call 루프 관리
  - Tool execution 결과 처리
  - Loop detection
- `core/agent.py`에 남는 것:
  - Intent 분류 → 라우팅
  - Orchestrator 위임
  - conversation_manager/tool_coordinator 조율

**handle_message() 분리:** 320줄 → 각 단계를 별도 메서드/클래스로 위임

### Stream 7: bootstrap_all() 리팩토링

**현재 문제:** 1064줄, 8 Phase, AppComponents 37개 필드

**분리 계획:**
- `core/bootstrap/` 패키지로 변환:
  - `components.py`: AppComponents를 계층화된 구성으로 분리
    - `DatabaseComponents`, `LLMComponents`, `MemoryComponents`, `PluginComponents`, `MessengerComponents`
  - `phases.py`: 각 Phase를 독립 함수로 분리
    - `init_phase_database()`, `init_phase_credentials()`, `init_phase_core_services()`, `init_phase_plugins()`, `init_phase_agent()`, `init_phase_messengers()`, `init_phase_background()`, `init_phase_personal()`
  - `orchestrator.py`: Phase 간 의존성 관리 및 순차 실행
- `core/bootstrap.py`는 하위 호환을 위해 re-export

### Stream 8: 설정 시스템 Pydantic 단일화

**현재 문제:** dataclass(`config.py`) + Pydantic(`config_schema.py`) + 프로필(`config_profiles.py`) 3중 공존

**통합 계획:**
- `config.py`의 dataclass 기반 설정 → Pydantic v2 BaseModel로 전환
- `config_schema.py`의 opt-in 검증 → 항상 활성화 (Pydantic 기본 동작)
- `config_profiles.py`의 프로필 병합 → Pydantic의 `model_config` 활용
- 환경변수 지원 → Pydantic의 `pydantic-settings` 활용

**마이그레이션:**
- 기존 `config.py`의 클래스들을 Pydantic BaseModel로 변환
- import 경로는 유지 (하위 호환)
- `config_types.py`도 Pydantic으로 통합

---

## 의존성 그래프

```
Stream 1 (데드코드) ──┐
Stream 2 (하드코딩) ──┤── 모두 완료 후 ──┬── Stream 6 (CoreAgent)
Stream 3 (데이터클래스)┤                  ├── Stream 7 (bootstrap)
Stream 4 (메신저) ────┤                  └── Stream 8 (설정)
Stream 5 (유틸리티) ──┘
```

Stream 1~5는 완전 독립. Stream 6~8은 기반 정리 완료 후 진행하되, 서로 간에도 독립적.

## 안전 장치

- 각 Stream은 git worktree에서 격리 실행
- 각 Stream 완료 후 `pytest tests/ -v --tb=short` 실행하여 회귀 검증
- Stream 병합 시 충돌 발생하면 수동 해결
- 아키텍처 변경(Stream 6~8)은 기존 인터페이스 유지하며 점진적 전환
