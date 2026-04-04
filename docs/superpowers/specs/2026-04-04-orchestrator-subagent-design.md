# Orchestrator + SubAgent Architecture Design

## Overview

BreadMind의 명령 실행 구조를 단일 CoreAgent 루프에서 **오케스트레이터 + 전문 subagent** 아키텍처로 전환한다. 메인 LLM은 오케스트레이터로 동작하고, 실제 작업은 전문 subagent를 통해 병렬 실행된다.

**접근법**: 하이브리드 — 명시적 DAG로 계획하되, 실행 중 결과에 따라 LLM이 DAG를 동적으로 수정/확장.

## 요구사항

| 항목 | 결정 |
|------|------|
| subagent 전문 분야 | 도메인 x 작업 유형 혼합 |
| LLM 전략 | 작업 난이도별 동적 모델 선택 |
| 의존성 처리 | DAG 초기 계획 + 결과 기반 동적 재계획 |
| 실패 대응 | 재시도 -> 대체 전략 -> 사용자 보고 |
| 기존 코드 | Swarm/SubAgent/delegate_tasks 완전 대체 |
| 도구 범위 | 역할 전용 도구 + 공용 도구 조합 |

## Architecture

### 전체 흐름

```
사용자 메시지
  -> CoreAgent.handle_message() (기존 진입점 유지)
      -> Intent 분류 -> 단순 작업이면 기존 단일 루프로 처리
      -> 복합 작업이면 Orchestrator 진입
          -> Planner: LLM 호출 -> TaskDAG 생성
          -> DAGExecutor: 의존성 순서대로 subagent 병렬 실행
              -> 각 완료 시 ResultEvaluator 판단
                  -> 정상: 다음 노드 진행
                  -> 이상: Orchestrator LLM 재호출 -> DAG 수정
          -> 전체 완료 -> Orchestrator LLM -> 최종 요약
  -> 응답 반환
```

### 핵심 컴포넌트 (5개)

| 컴포넌트 | 역할 | 위치 |
|----------|------|------|
| **Orchestrator** | 진입 판단, Planner/DAGExecutor 조율, 최종 요약 생성 | `core/orchestrator.py` |
| **Planner** | 사용자 요청을 TaskDAG로 분해 (LLM 호출) | `core/planner.py` |
| **DAGExecutor** | TaskDAG를 의존성 순서대로 실행, subagent 스폰/수집 | `core/dag_executor.py` |
| **SubAgent** | 개별 작업 실행 (자체 LLM 루프 + 역할 전용 도구) | `core/subagent.py` (대체) |
| **ResultEvaluator** | subagent 결과의 정상/이상 판단 | `core/result_evaluator.py` |

### CoreAgent와의 관계

CoreAgent는 기존대로 단일 루프 에이전트로 유지된다. Orchestrator는 CoreAgent 내부에서 "복합 작업"일 때만 활성화되는 경로이다. 단순 질문("K8s Pod 목록 보여줘")은 기존 루프로 처리하고, 복합 명령("느린 Pod 진단하고 수정해줘")만 Orchestrator 경로로 분기한다.

**분기 기준**: Intent 분류 결과의 복잡도 판단 - 다중 도메인, 다중 단계, 진단+실행 조합 등이 감지되면 Orchestrator로 전환.

## Planner

고성능 LLM(Opus)을 호출하여 사용자 요청을 구조화된 TaskDAG로 변환한다. 1회 호출로 전체 계획을 생성한다.

### TaskDAG 데이터 모델

```python
@dataclass
class TaskNode:
    id: str                          # "task_1", "task_2", ...
    description: str                 # 작업 설명
    role: str                        # "k8s_diagnostician", "proxmox_provisioner" 등
    depends_on: list[str]            # 선행 작업 ID
    difficulty: str                  # "low" | "medium" | "high" -> 모델 선택 기준
    tools: list[str]                 # 역할 전용 도구 (빈 목록이면 역할 기본 도구셋)
    expected_output: str             # 기대 결과 설명 (ResultEvaluator가 판단 기준으로 사용)
    max_retries: int = 2             # 재시도 횟수

@dataclass
class TaskDAG:
    goal: str                        # 원래 사용자 요청
    nodes: dict[str, TaskNode]       # id -> TaskNode
    context: dict                    # 공유 컨텍스트 (이전 subagent 결과 누적)
```

### 역할 정의 (도메인 x 작업 유형)

역할은 `{domain}_{task_type}` 패턴으로 구성된다:

```
도메인: k8s, proxmox, openwrt, db, network, general
작업 유형: diagnostician, executor, monitor, coder, analyst
```

각 역할에는 미리 정의된 전용 도구 세트 + 공용 도구가 매핑된다:

```python
ROLE_TOOLSETS = {
    "k8s_diagnostician": {
        "dedicated": ["pods_list", "pods_log", "events_list", "nodes_top", "pods_top"],
        "common": ["shell_exec", "file_read", "web_search"],
    },
    "proxmox_executor": {
        "dedicated": ["proxmox_get_vms", "proxmox_start_vm", "proxmox_stop_vm", ...],
        "common": ["shell_exec", "file_read", "file_write"],
    },
    # ...
}
```

### 난이도 -> 모델 매핑

```python
DIFFICULTY_MODEL = {
    "low": "haiku",       # 단순 조회, 상태 확인
    "medium": "sonnet",   # 분석, 설정 변경
    "high": "opus",       # 복합 진단, 위험한 작업
}
```

### 권장 사항

- Planner 프롬프트에 사용 가능한 역할 목록과 도구셋을 명시하여 LLM이 적절한 역할을 선택하도록 유도
- JSON 출력 강제를 위해 structured output 또는 tool_use 방식 활용
- 단일 도메인 + 단일 작업이면 Planner가 노드 1개짜리 DAG를 반환하여 subagent 1개로 실행

## DAGExecutor

DAG의 노드를 위상 정렬하여, 의존성이 해소된 노드들을 `asyncio.gather`로 병렬 스폰한다.

### 실행 흐름

1. 의존성 없는 노드들을 한 배치로 병렬 실행
2. 각 subagent 완료 -> 결과를 `TaskDAG.context`에 누적
3. ResultEvaluator로 정상/이상 판단
4. 정상이면 후속 노드 의존성 해소 -> 다음 배치 실행
5. 이상이면 Orchestrator에 재계획 요청

### 권장 사항

- 동시 실행 subagent 수 제한 (기본 5개)
- 노드별 타임아웃은 difficulty 기반 (low: 60s, medium: 180s, high: 600s)
- 진행률을 WebSocket progress callback으로 실시간 전송

## SubAgent

각 SubAgent는 독립된 LLM 대화 루프를 가진다. 기존 CoreAgent의 축소판이다.

### 구성

- 역할 기반 시스템 프롬프트 (Jinja2 템플릿)
- 역할 전용 도구 + 공용 도구
- 난이도 기반 LLM 모델 선택
- 선행 작업 결과를 컨텍스트로 주입

### 권장 사항

- max_turns는 difficulty 기반 (low: 3, medium: 5, high: 10)
- SafetyGuard는 기존 것을 공유 (승인 필요 시 Orchestrator로 에스컬레이션)
- subagent는 Working Memory를 갖지 않음 (세션 내 일회성)

## ResultEvaluator

subagent 결과를 `expected_output`과 비교하여 판단한다.

### 판단 기준 (규칙 기반 우선)

1. `[success=False]` -> 이상 (실패)
2. 출력이 비어있음 -> 이상
3. 타임아웃 -> 이상

위 규칙에 해당하지 않으면 정상으로 간주한다.

### 권장 사항

- 규칙으로 판단 불가한 경우, 경량 LLM(Haiku)으로 `expected_output` 대비 결과 적합성 평가
- 이상 판단 시 `failure_reason`을 구조화하여 Orchestrator 재계획에 활용

## 실패 대응 - 3단계 폴백

```
1단계: 재시도
  -> 같은 subagent를 max_retries까지 재실행
  -> 재시도 시 이전 실패 결과를 컨텍스트에 포함

2단계: 대체 전략
  -> Orchestrator LLM 호출: 실패 원인 + 기존 DAG 전달
  -> LLM이 대체 노드 생성 (다른 도구/접근법)
  -> DAG에 대체 노드 삽입 후 실행 계속

3단계: 사용자 보고
  -> 대체 전략도 실패 시 실행 중단
  -> 지금까지의 성공 결과 + 실패 내역을 요약하여 사용자에게 반환
```

### 권장 사항

- 대체 전략 시도는 최대 1회로 제한 (무한 재계획 방지)
- 실패 보고에는 성공한 노드의 결과도 포함 (부분 성공 활용)

## 기존 코드 대체 범위

| 기존 코드 | 처리 | 이유 |
|-----------|------|------|
| `core/swarm.py`, `core/swarm_executor.py` | **삭제** | DAGExecutor가 대체 |
| `core/subagent.py` (SubAgentManager) | **대체** | 새 SubAgent로 교체 |
| `core/team_builder.py` | **흡수** | 역할 선택 로직을 Planner에 통합 |
| `tools/builtin.py`의 `delegate_tasks` | **삭제** | Orchestrator가 대체 |
| `coding/tool.py` (code_delegate) | **유지** | 외부 코딩 에이전트 위임은 subagent 도구로 편입 |
| `core/agent.py` (CoreAgent) | **수정** | 복합 작업 분기 로직 추가 |
| `web/routes/subagent.py` | **수정** | 새 Orchestrator API에 맞게 갱신 |

## 데이터 흐름 예시

```
사용자: "K8s OOMKilled Pod 찾아서 메모리 2배로 올리고, Proxmox에서 리소스 여유 확인해줘"

1. CoreAgent -> Intent: 복합 작업 (다중 도메인 + 진단+실행)
2. Orchestrator 진입
3. Planner (Opus) -> DAG:
   +-- task_1: K8s OOMKilled Pod 조회 (k8s_diagnostician, low)
   +-- task_2: Proxmox 노드 리소스 확인 (proxmox_analyst, low)  <- task_1과 병렬
   +-- task_3: Pod 메모리 limit 확인 (k8s_diagnostician, low, depends: task_1)
   +-- task_4: 메모리 limit 2배 적용 (k8s_executor, medium, depends: task_3)

4. DAGExecutor:
   배치 1: task_1 (Haiku) + task_2 (Haiku) -> 병렬 실행
   -> ResultEvaluator: 둘 다 정상
   배치 2: task_3 (Haiku) -> 실행
   -> ResultEvaluator: 정상
   배치 3: task_4 (Sonnet) -> 실행
   -> ResultEvaluator: 정상

5. Orchestrator (Opus) -> 전체 결과 요약하여 사용자에게 응답
```
