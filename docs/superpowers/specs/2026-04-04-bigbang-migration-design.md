# v1→v2 빅뱅 마이그레이션 설계

## 목표

v2 프레임워크 코드의 `v2_` 접두사 및 `v2_builtin/` 분리를 제거하고, v1 코드와 통합하여 단일 코드베이스로 만든다.

## 결정 사항

| 항목 | 결정 |
|------|------|
| EventBus | v2로 완전 교체. v1 소비자를 v2 인터페이스로 마이그레이션 |
| container.py | v1 ContainerExecutor를 `core/sandbox.py`로 이동. v2 Container가 `core/container.py` 차지 |
| plugins/builtin/ | v2_builtin/ 하위를 builtin/에 합치기. v1 플러그인과 공존 |

## 변경 상세

### 1. EventBus — v2로 완전 교체

- v1 `core/events.py` 삭제
- v2 `core/v2_events.py` → `core/events.py`로 이동
- v2 EventBus에 `get_event_bus()` 싱글턴 함수 추가
- v1 소비자 6개 파일 마이그레이션:
  - `EventType.SESSION_START` → `"session_start"` 문자열
  - `Event(type=..., data=..., source=...)` → data dict 직접 전달
  - `publish_fire_and_forget(Event(...))` → `await async_emit("event_name", {...})`

### 2. Container — v1을 sandbox.py로 이동

- v1 `core/container.py` → `core/sandbox.py` (ContainerExecutor)
- v2 `core/v2_container.py` → `core/container.py` (DI Container)
- v1 소비자 2곳 import 변경

### 3. Plugin — v2를 core/plugin.py로

- v2 `core/v2_plugin.py` → `core/plugin.py`
- v1 플러그인 시스템은 그대로 유지

### 4. plugins/builtin/ — v2 합치기

- `plugins/v2_builtin/*` → `plugins/builtin/*`에 이동
- v1 기존 디렉토리(core_tools, network, browser, coding, messenger, personal)와 v2 신규 디렉토리(agent_loop, providers, safety, tools, memory, runtimes, domains) 공존
- 이름 충돌 없음

### 5. Import 변경 범위

| 카테고리 | 파일 수 | 변경 내용 |
|----------|---------|-----------|
| v1 EventBus 소비자 | 6 | EventType/Event → string 기반 |
| v1 ContainerExecutor 소비자 | 2 | container → sandbox |
| v2 내부 import (v2_ 접두사) | ~8 | v2_events → events 등 |
| v2 내부 import (v2_builtin) | ~20 | v2_builtin → builtin |
| 테스트 파일 | ~21 | 위와 동일 패턴 |
| **총계** | **~57 파일** | |
