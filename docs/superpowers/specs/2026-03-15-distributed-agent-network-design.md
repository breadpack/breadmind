# Distributed Agent Network Design

**Date**: 2026-03-15
**Status**: Approved

## Overview

BreadMind의 확장성을 극대화하기 위해 관리 대상 인프라 노드에 하위 Worker 에이전트를 자동 배포하여, 중앙 Commander와 연동하는 분산 에이전트 네트워크를 구축한다. 각 Worker는 로컬에서 도구를 실행하고, cron 작업/모니터링/역할 수행 및 보고를 담당한다.

## Architecture

### Approach: Mesh Agent Network

하나의 코드베이스, 두 가지 실행 모드 (Commander / Worker).

```
┌─────────────────────────────────────────────────┐
│              Central BreadMind (Commander)        │
│                                                   │
│  ┌─────────┐ ┌──────────┐ ┌───────────────────┐ │
│  │ CA/PKI  │ │ LLM      │ │ Agent Registry    │ │
│  │ Manager │ │ Proxy    │ │ + Role Manager    │ │
│  └─────────┘ └──────────┘ └───────────────────┘ │
│  ┌─────────────────────────────────────────────┐ │
│  │         WebSocket Hub (Relay Server)         │ │
│  └──────┬──────────┬──────────────┬────────────┘ │
│         │          │              │               │
│  ┌──────┴───┐ ┌────┴─────┐ ┌─────┴──────┐       │
│  │ Existing │ │ Task     │ │ Sync       │       │
│  │ CoreAgent│ │ Dispatch │ │ Manager    │       │
│  └──────────┘ └──────────┘ └────────────┘       │
└─────────────────────────────────────────────────┘
         │ mTLS          │ mTLS         │ mTLS
    ┌────▼─────┐   ┌─────▼────┐   ┌────▼─────┐
    │ Worker   │   │ Worker   │   │ Worker   │
    │ @k8s-n1  │   │ @pve-h1  │   │ @owrt-gw │
    │          │   │          │   │          │
    │ Executor │   │ Executor │   │ Executor │
    │ Scheduler│   │ Scheduler│   │ Scheduler│
    │ Local Q  │   │ Local Q  │   │ Local Q  │
    └──────────┘   └──────────┘   └──────────┘
```

### Key Design Decisions

- **LLM**: Worker가 직접 LLM을 호출하지 않고 Commander를 프록시로 사용 (API 키 중앙 관리, 비용 통제)
- **통신**: WebSocket 양방향 실시간 (Worker → Commander outbound 연결, 방화벽 친화적)
- **배포**: Commander가 환경 감지하여 Docker/LXC/SSH 직접 설치 자동 선택
- **오프라인**: 할당된 cron/모니터링은 계속 수행, LLM 필요 작업은 큐잉 후 재연결 시 처리
- **역할**: Commander가 런타임에 동적 할당·변경
- **보안**: mTLS 상호 인증, Commander가 CA 역할

## Components

### New Modules

```
src/breadmind/
  network/                    # 새 패키지
    __init__.py
    commander.py              # WebSocket Hub, Worker 관리, 태스크 디스패치
    worker.py                 # Worker 런타임 (경량 CoreAgent 변형)
    protocol.py               # 메시지 envelope 정의, 직렬화/역직렬화
    pki.py                    # CA 관리, 인증서 발급/갱신/폐기
    registry.py               # Agent Registry (등록, 상태, 역할 매핑)
    sync.py                   # 오프라인 결과 동기화

  deploy/                     # 새 패키지 (기존 deploy/install과 별도)
    __init__.py
    provisioner.py            # 환경 감지 + 배포 방식 선택 로직
    strategies/
      __init__.py
      kubernetes.py           # DaemonSet 배포
      proxmox.py              # LXC 컨테이너 생성 + 설치
      ssh.py                  # 직접 SSH 설치
    templates/                # Worker 설정 템플릿
      worker-config.yaml.j2
      worker-compose.yaml.j2
```

### Existing Module Changes

| Module | Change |
|--------|--------|
| `config.py` | `NetworkConfig` 추가 (commander/worker 모드, ws 포트, mTLS 경로) |
| `main.py` | 시작 모드 분기: `--mode commander` or `--mode worker` |
| `core/agent.py` | Worker 모드 시 LLM 호출을 WebSocket 프록시로 위임 |
| `core/safety.py` | `agent_id` 필드 추가, Worker 역할 기반 정책 필터링 |
| `tools/registry.py` | Worker 모드 시 역할에 허용된 도구만 등록 |
| `web/app.py` | `/ws/agent/{agent_id}` 엔드포인트 추가, Agent Registry UI |
| `monitoring/engine.py` | Worker heartbeat 모니터링 통합 |

## Worker Lifecycle

### State Machine

```
[Unprovisioned] → deploy → [Starting]
[Starting] → ws_connect → [Registering]
[Registering] → registered → [Idle]
[Idle] → role_assigned → [Active]
[Active] → ws_lost → [Offline]
[Offline] → ws_reconnect → [Syncing]
[Syncing] → sync_done → [Active]
[Active] → decommission → [Draining]
[Draining] → tasks_done → [Removed]
```

### Deployment Strategies

1. **환경 감지** — 중앙이 기존 접근 경로(SSH, K8s API, Proxmox API)를 통해 대상 OS, 런타임, 컨테이너 엔진 확인
2. **배포 방식 결정**:
   - K8s 노드 → DaemonSet으로 Worker Pod 배포
   - Proxmox 호스트 → LXC 컨테이너 생성 후 Worker 설치
   - 일반 Linux/OpenWrt → SSH로 직접 바이너리/스크립트 설치
3. **인증서 발급** — CA Manager가 Worker 전용 클라이언트 인증서 생성, 배포 시 주입
4. **초기 등록** — Worker 첫 기동 시 WebSocket 연결, 환경 정보 보고
5. **역할 할당 대기** — 등록 완료 후 Commander가 역할 할당

### Heartbeat & Health

- Worker → Commander: 30초 간격 (CPU, 메모리, 디스크, 큐 크기)
- Commander: 90초 응답 없으면 `Offline` 마킹, 긴급 태스크 재할당
- 재연결 시: Local Queue bulk 전송 후 `Active` 복귀

### Update & Decommission

- **업데이트** — Commander가 새 버전 감지 시 Worker에 업데이트 명령, Worker 자체 rolling restart
- **제거** — Draining → 진행 중 태스크 완료 대기 → 인증서 폐기 → 에이전트 삭제

## Communication Protocol

### WebSocket Connection

- Worker가 outbound 연결 시작: `wss://commander:8080/ws/agent/{agent_id}`
- mTLS 핸드셰이크로 양측 인증

### Message Envelope

```json
{
  "id": "uuid",
  "type": "task_assign | task_result | llm_request | llm_response | heartbeat | sync | role_update | command",
  "source": "commander | agent_id",
  "target": "commander | agent_id",
  "timestamp": "ISO8601",
  "payload": {},
  "reply_to": "uuid (optional)"
}
```

### Message Types

| Type | Direction | Purpose |
|------|-----------|---------|
| `task_assign` | Commander → Worker | 태스크 할당 (즉시 실행 or cron 등록) |
| `task_result` | Worker → Commander | 실행 결과 보고 |
| `llm_request` | Worker → Commander | LLM 추론 요청 |
| `llm_response` | Commander → Worker | LLM 응답 반환 |
| `heartbeat` | Worker → Commander | 상태 보고 |
| `sync` | Worker → Commander | 오프라인 결과 bulk 전송 |
| `role_update` | Commander → Worker | 역할 변경 |
| `command` | Commander → Worker | 직접 명령 (재시작, 업데이트, 제거) |

### LLM Proxy Flow

```
Worker: 판단 필요
  → llm_request {prompt, context, tools_available}
  → Commander: LLM Provider에 요청 (rate limit, 비용 체크)
  → llm_response {content, tool_calls}
  → Worker: tool_calls 로컬 실행
  → (반복 가능, 태스크당 최대 10턴)
  → task_result 보고
```

### Offline Queuing

- 스케줄된 태스크는 계속 실행, LLM 필요 단계는 skip
- 결과는 SQLite 저장: `{task_id, result, timestamp, needs_llm}`
- 재연결 시 `sync` 메시지로 일괄 전송, `needs_llm: true` 항목은 Commander가 후처리

## Role Assignment & Task Management

### Role Definition

```json
{
  "role_id": "uuid",
  "name": "k8s-node-monitor",
  "description": "K8s 노드 상태 모니터링 및 이상 시 자동 대응",
  "tools": ["shell_exec", "file_read", "mcp:kubernetes"],
  "schedules": [
    {"type": "cron", "expr": "*/1 * * * *", "task": "check_pod_status"},
    {"type": "cron", "expr": "*/5 * * * *", "task": "check_node_resources"}
  ],
  "policies": {
    "auto_actions": ["restart_pod", "drain_node"],
    "require_approval": ["delete_pod", "cordon_node"],
    "blocked": ["delete_namespace", "reset_cluster"]
  },
  "escalation": {
    "on_failure_count": 3,
    "action": "notify_commander"
  }
}
```

### Role Assignment Flow

1. 사용자 요청 또는 Commander 자동 추천
2. `role_update` 메시지로 Worker에 역할 정의 전달
3. Worker: Scheduler에 cron 등록, 도구/정책 적용
4. 변경: 언제든 `role_update`로 추가·수정·제거 가능

### Task Types

| Type | Description | Example |
|------|-------------|---------|
| `scheduled` | cron 기반 반복 | 1분마다 pod 상태 체크 |
| `on_demand` | Commander 즉시 요청 | nginx 로그 조회 |
| `reactive` | 로컬 이벤트 트리거 | 디스크 90% 초과 시 정리 |
| `long_running` | 지속 실행 | 로그 스트리밍, 파일 감시 |

### Escalation

- 동일 태스크 연속 3회 실패 → Commander 에스컬레이션
- Commander의 CoreAgent가 상위 판단
- 필요시 사용자 알림 (기존 메신저 채널)

## Security Model

### mTLS PKI

```
BreadMind CA (자체 서명 Root)
  ├── Commander 서버 인증서
  ├── Worker 클라이언트 인증서 @k8s-node1
  ├── Worker 클라이언트 인증서 @pve-host1
  └── Worker 클라이언트 인증서 @openwrt-gw
```

- **CA 키** — Commander의 암호화된 저장소에 보관 (Fernet 기반)
- **인증서 수명** — Worker 인증서 90일, 만료 7일 전 자동 갱신
- **폐기** — CRL 업데이트, 모든 Worker에 전파

### Permission Hierarchy

- Commander: full authority
- Worker: 역할 정의에 명시된 도구/정책만 실행 가능
- Worker 로컬 Safety Guard가 역할 범위 밖 tool_call 차단

### Threat Model

| Threat | Mitigation |
|--------|------------|
| Worker 인증서 탈취 | CRL 즉시 업데이트, Worker 강제 제거 |
| 악의적 LLM 응답 | Worker 로컬 Safety Guard blocked 정책 |
| Worker 노드 침해 | 역할 범위 제한으로 blast radius 최소화 |
| 중간자 공격 | mTLS 양방향 인증 |
| Commander 침해 | 백업 CA 키, 감사 로그 외부 전송 |

### Audit Logging

- 모든 Worker 태스크/LLM 호출/도구 사용을 Commander에 기록
- 기존 audit_log 테이블에 `agent_id` 필드 추가

## Database Schema

### Commander (PostgreSQL) — New Tables

```sql
CREATE TABLE agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL,
    host VARCHAR(256) NOT NULL,
    status VARCHAR(20) DEFAULT 'registering',
    environment JSONB,
    cert_fingerprint VARCHAR(64),
    cert_expires_at TIMESTAMPTZ,
    last_heartbeat TIMESTAMPTZ,
    registered_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE agent_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) UNIQUE NOT NULL,
    definition JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE agent_role_assignments (
    agent_id UUID REFERENCES agents(id) ON DELETE CASCADE,
    role_id UUID REFERENCES agent_roles(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (agent_id, role_id)
);

CREATE TABLE agent_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES agents(id),
    role_id UUID REFERENCES agent_roles(id),
    type VARCHAR(20) NOT NULL,
    params JSONB,
    status VARCHAR(20) DEFAULT 'pending',
    result JSONB,
    metrics JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE agent_certificates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES agents(id) ON DELETE CASCADE,
    fingerprint VARCHAR(64) NOT NULL,
    issued_at TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT true
);
```

### Existing Table Changes

```sql
ALTER TABLE audit_log ADD COLUMN agent_id UUID REFERENCES agents(id);
```

### Worker (SQLite) — Local Schema

```sql
CREATE TABLE offline_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    result TEXT NOT NULL,
    needs_llm BOOLEAN DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    synced_at TEXT
);

CREATE TABLE task_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT,
    executed_at TEXT DEFAULT (datetime('now'))
);
```

## Execution Modes

```bash
# Commander (기존 기능 + 네트워크 레이어)
breadmind --mode commander

# Worker (경량 모드)
breadmind --mode worker --commander wss://central:8080/ws/agent/self
```

Worker 모드에서는 Web UI, 메신저 연동, Swarm, 메모리 시스템이 로드되지 않음. Executor + Scheduler + Local Queue + WebSocket 클라이언트만 기동.
