# Behavior Prompt Self-Improvement System

## Overview

BreadMind의 행동 프롬프트(`_PROACTIVE_BEHAVIOR_PROMPT`)를 매 대화 종료 후 자동으로 분석·개선하는 시스템. 전체 대화 컨텍스트를 기반으로 LLM이 현재 프롬프트의 부족한 점을 찾아 개선안을 생성하고, 즉시 적용한 뒤 사용자에게 알린다.

## Design Decisions

| 결정 항목 | 선택 | 이유 |
|-----------|------|------|
| 분석 단위 | 매 대화 종료 후 | 즉각적 피드백 반영 |
| 적용 방식 | 자동 적용 + 알림 | 사용자 개입 없이 빠르게 반영하되 투명성 유지 |
| 입력 데이터 | 전체 대화 컨텍스트 | 도구 패턴, 사용자 피드백, 질문-도구 매핑 모두 활용 |
| 이력 관리 | 최신 버전만 유지 | 단순성 우선 |
| 분석 LLM | 기본 LLM과 동일 | 별도 설정 불필요 |

## Components

### BehaviorTracker (`src/breadmind/core/behavior_tracker.py`)

단일 클래스로 데이터 수집, 분석, 프롬프트 업데이트를 담당.

```python
class BehaviorTracker:
    def __init__(self, provider, get_behavior_prompt, set_behavior_prompt, db=None):
        """
        provider: LLMProvider — 분석용 LLM
        get_behavior_prompt: Callable[[], str] — 현재 행동 프롬프트 조회
        set_behavior_prompt: Callable[[str], None] — 행동 프롬프트 업데이트
        db: Database | None — 영속화용
        """
        self._lock = asyncio.Lock()  # 동시 분석 방지
```

#### 수집 데이터 (메시지 리스트에서 추출)

- **도구 사용 여부**: 도구 호출 없이 텍스트만 응답했는지
- **도구 호출 결과**: 각 도구의 성공/실패
- **사용자 메시지 → 도구 선택 매핑**: 어떤 질문에 어떤 도구를 선택했는지
- **사용자 피드백 감지**: 부정적("그게 아니라", "아닌데", "왜 안 해?") / 긍정적("잘했어", "고마워") 반응

#### 최소 대화 길이

사용자 메시지가 2개 미만이거나 총 메시지가 4개 미만인 대화는 분석하지 않음 (인사, 단답 등 제외).

#### 분석 프롬프트

현재 행동 프롬프트 + 대화 데이터를 LLM에 전달하여:
- 현재 프롬프트의 부족한 점 식별
- 구체적 개선안 생성 (기존 프롬프트 형식 유지)
- 개선이 불필요하면 정확히 `NO_CHANGE`만 응답

LLM 응답 형식:
```
NO_CHANGE
```
또는:
```
REASON: 변경 사유 한 줄 요약
---
개선된 프롬프트 전문
```

#### 프롬프트 크기 제한

개선된 프롬프트가 2000자를 초과하면 적용하지 않고 로그 경고.

#### 대화 컨텍스트 요약

분석 시 전체 대화를 그대로 전달하지 않고, 메시지 리스트에서 구조화된 요약을 추출하여 전달:
- 사용자 메시지 목록 (최대 10개, 각 200자 제한)
- 도구 호출 목록: 도구명, 성공/실패
- 텍스트 전용 응답 여부
- 감지된 사용자 피드백

#### 개선안 적용

1. `set_behavior_prompt(new_prompt)` 콜백으로 런타임 적용
2. `db.set_setting("behavior_prompt", data)`로 영속화
3. 반환값으로 변경 사유를 돌려줌 (알림은 호출자가 처리)

### 행동 프롬프트 분리: build_system_prompt 변경

`build_system_prompt`에 `behavior_prompt` 파라미터를 추가하여, 행동 프롬프트 부분만 교체 가능하게 한다.

```python
def build_system_prompt(persona: dict, behavior_prompt: str | None = None) -> str:
    parts = [persona.get("system_prompt", ...)]
    # ... language, specialties, name ...
    parts.append(behavior_prompt or _PROACTIVE_BEHAVIOR_PROMPT)
    return "\n\n".join(parts)
```

CoreAgent에 행동 프롬프트 getter/setter 추가:

```python
class CoreAgent:
    def __init__(self, ..., behavior_prompt: str | None = None):
        self._behavior_prompt = behavior_prompt or _PROACTIVE_BEHAVIOR_PROMPT

    def get_behavior_prompt(self) -> str:
        return self._behavior_prompt

    def set_behavior_prompt(self, prompt: str):
        self._behavior_prompt = prompt
        # rebuild full system prompt with updated behavior portion
        self._system_prompt = build_system_prompt(
            self._persona, behavior_prompt=prompt
        )
```

이로써 페르소나/언어/전문분야는 유지하면서 행동 프롬프트만 교체된다.

### CoreAgent 통합

`handle_message` 반환 직전에 `BehaviorTracker.analyze()`를 **fire-and-forget** (`asyncio.create_task`)으로 호출. `asyncio.Lock`으로 동시 분석 방지. 전체를 try/except로 감싸서 실패 시 로그만 남김.

```python
# handle_message 끝
if self._behavior_tracker is not None:
    asyncio.create_task(
        self._safe_analyze(session_id, list(messages), channel)
    )

async def _safe_analyze(self, session_id, messages, channel):
    try:
        result = await self._behavior_tracker.analyze(session_id, messages)
        if result:
            logger.info(f"Behavior prompt improved: {result['reason']}")
    except Exception:
        logger.exception("Behavior analysis failed")
```

### 알림

`analyze()`는 변경 사유만 반환한다. 알림 전송은 `handle_message` 호출자(web app, messenger gateway)가 처리한다. 이유:
- BehaviorTracker가 메신저 인프라에 의존하지 않음
- CLI/Web/Slack 등 채널별 알림 방식이 다름
- 비동기 분석 결과를 WebSocket이나 다음 응답에 포함하는 방식으로 전달

구현: CoreAgent에 `pending_notifications` 큐를 두고, 다음 `handle_message` 호출 시 응답 앞에 알림을 추가.

```python
class CoreAgent:
    def __init__(self, ...):
        self._notifications: list[str] = []

    async def handle_message(self, message, user, channel):
        # 알림이 있으면 응답 앞에 추가
        prefix = ""
        if self._notifications:
            prefix = "\n".join(self._notifications) + "\n\n"
            self._notifications.clear()
        # ... 기존 로직 ...
        return prefix + final_content
```

### 시작 시 로드

`main.py`에서:
1. DB에서 `behavior_prompt` 설정 로드
2. 있으면 `CoreAgent(behavior_prompt=saved_prompt)` 전달
3. 없으면 `_PROACTIVE_BEHAVIOR_PROMPT` 기본값 사용

## Data Flow

```
사용자 메시지 → CoreAgent.handle_message()
  ↓
[pending notifications 있으면 응답 앞에 추가]
  ↓
대화 처리 (도구 호출 루프)
  ↓
최종 응답 반환
  ↓ (fire-and-forget, asyncio.Lock으로 직렬화)
BehaviorTracker.analyze(session_id, messages)
  ↓
대화 길이 < 최소 기준? → 종료
  ↓
구조화된 요약 추출 (토큰 절약)
  ↓
LLM 분석 요청: current_prompt + summary → improved_prompt | NO_CHANGE
  ↓
NO_CHANGE → 종료
  ↓
프롬프트 > 2000자? → 로그 경고, 종료
  ↓
set_behavior_prompt(new_prompt) → CoreAgent 런타임 반영
  ↓
DB 저장 (behavior_prompt)
  ↓
CoreAgent._notifications에 변경 알림 추가
```

## Storage

```python
# DB key
"behavior_prompt": {
    "prompt": "개선된 프롬프트 전문",
    "updated_at": "2026-03-15T10:30:00Z",
    "reason": "변경 사유 요약"
}
```

## File Changes

| 파일 | 변경 내용 |
|------|-----------|
| `src/breadmind/core/behavior_tracker.py` | **신규** — BehaviorTracker 클래스 |
| `src/breadmind/core/agent.py` | `_behavior_prompt` 필드, getter/setter, `_notifications` 큐, `_safe_analyze` 호출 |
| `src/breadmind/main.py` | BehaviorTracker 생성, DB에서 behavior_prompt 로드 |
| `src/breadmind/config.py` | `build_system_prompt`에 `behavior_prompt` 파라미터 추가 |
