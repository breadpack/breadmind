# Distributed Agent Network Design

**Date**: 2026-03-15
**Status**: Approved

## Overview

BreadMind의 확장성을 극대화하기 위해 관리 대상 인프라 노드에 하위 Worker 에이전트를 자동 배포하여, 중앙 Commander와 연동하는 분산 에이전트 네트워크를 구축한다. 각 Worker는 로컬에서 도구를 실행하고, cron 작업/모니터링/역할 수행 및 보고를 담당한다.

## Architecture

### Approach: Hub-and-Spoke Agent Network

하나의 코드베이스, 두 가지 실행 모드 (Commander / Worker). Worker는 Commander하고만 통신하는 star 토폴로지.

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

**Future extension**: Worker-to-Worker 직접 통신 (P2P mesh)은 향후 확장으로 고려. 현재는 hub-and-spoke만 구현.

### Key Design Decisions

- **LLM**: Worker가 직접 LLM을 호출하지 않고 Commander를 프록시로 사용 (API 키 중앙 관리, 비용 통제)
- **통신**: WebSocket 양방향 실시간 (Worker → Commander outbound 연결, 방화벽 친화적)
- **배포**: Commander가 환경 감지하여 Docker/LXC/SSH 직접 설치 자동 선택
- **오프라인**: 할당된 cron/모니터링은 계속 수행, LLM 필요 작업은 큐잉 후 재연결 시 처리
- **역할**: Commander가 런타임에 동적 할당·변경
- **보안**: mTLS 상호 인증 + 메시지 HMAC + 코드 서명, Commander가 CA 역할

### Relationship with Existing Swarm

기존 `SwarmManager`는 **단일 인스턴스 내 LLM 페르소나 기반 멀티에이전트** (k8s_expert, security_analyst 등). 분산 Agent Network는 **물리적으로 분리된 노드에서의 도구 실행**. 두 시스템의 관계:

- Commander의 Swarm expert가 특정 태스크를 수행할 때, 해당 도메인의 Worker에게 로컬 실행을 위임할 수 있음
- Worker는 Swarm을 내부적으로 실행하지 않음 (Worker는 단일 에이전트)
- 향후 Worker가 복잡해지면 자체 Swarm을 탑재할 수 있으나, 현재 범위 밖

## Components

### New Modules

```
src/breadmind/
  network/                    # 새 패키지
    __init__.py
    commander.py              # WebSocket Hub, Worker 관리, 태스크 디스패치
    worker.py                 # Worker 런타임 (경량 CoreAgent 변형)
    protocol.py               # 메시지 envelope 정의, 직렬화/역직렬화, HMAC 검증
    pki.py                    # CA 관리, 인증서 발급/갱신/폐기, 코드 서명
    registry.py               # Agent Registry (등록, 상태, 역할 매핑)
    sync.py                   # 오프라인 결과 동기화, 태스크 중복 방지

  provisioning/               # 새 패키지 (deploy/와 이름 충돌 방지)
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
| `config.py` | `NetworkConfig` 추가 (commander/worker 모드, ws 포트, mTLS 경로, LLM quota) |
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
- Commander: 90초 응답 없으면 `Offline` 마킹
- 태스크 재할당 시 idempotency key 기반 중복 방지 (아래 Task Idempotency 참조)
- 재연결 시: Local Queue bulk 전송 후 `Active` 복귀

### Update & Decommission

- **업데이트** — Commander가 새 버전 감지 시 서명된 업데이트 패키지 전송, Worker가 코드 서명 검증 후 적용 (서명 키는 CA 키와 별도 관리)
- **제거** — Draining → 진행 중 태스크 완료 대기 → 인증서 폐기 → 에이전트 삭제

### Resource Requirements

| Target | Min RAM | Min Storage | Runtime |
|--------|---------|-------------|---------|
| K8s Node | 256MB | 500MB | Python 3.11+ (Docker) |
| Proxmox Host | 256MB | 500MB | Python 3.11+ (LXC) |
| Linux Server | 128MB | 300MB | Python 3.11+ |
| OpenWrt | 64MB | 100MB | MicroPython or Go lightweight binary (향후) |

**Known limitation**: OpenWrt의 메모리 제약(128MB)으로 인해 전체 Python 런타임이 부담될 수 있음. 초기 구현은 Python 기반으로 통일하되, OpenWrt 전용 경량 Worker 바이너리(Go/Rust)는 향후 확장으로 고려.

## Communication Protocol

### WebSocket Connection

- Worker가 outbound 연결 시작: `wss://commander:8080/ws/agent/{agent_id}`
- mTLS 핸드셰이크로 양측 인증
- Commander는 매 핸드셰이크 시 CRL(인증서 폐기 목록)을 확인하여 폐기된 인증서의 재연결 차단

### Message Envelope

```json
{
  "protocol_version": 1,
  "id": "uuid",
  "seq": 12345,
  "type": "task_assign | task_result | llm_request | llm_response | heartbeat | sync | role_update | command",
  "source": "commander | agent_id",
  "target": "commander | agent_id",
  "timestamp": "ISO8601",
  "trace_id": "uuid (optional, for cross-node tracing)",
  "payload": {},
  "reply_to": "uuid (optional)",
  "hmac": "SHA256 HMAC of message body"
}
```

**Protocol versioning**: `protocol_version` 필드로 호환성 관리. Worker 등록 시 capability negotiation 수행. 알 수 없는 메시지 타입은 로그 경고 후 무시.

**Message integrity**: 모든 메시지에 세션 키 기반 HMAC 포함. 세션 키는 WebSocket 연결 시 mTLS 핸드셰이크에서 파생. `seq` 필드로 replay attack 방지 (양측이 monotonic sequence 검증).

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
  → Commander: LLM Provider에 요청 (rate limit, 비용 체크, Worker별 quota 확인)
  → llm_response {content, tool_calls}
  → Worker: tool_calls 로컬 실행
  → (반복 가능, 태스크당 최대 10턴)
  → task_result 보고
```

### LLM Proxy Rate Limiting

| Limit | Default | Description |
|-------|---------|-------------|
| Per-Worker RPM | 30 | Worker당 분당 최대 LLM 요청 수 |
| Per-Worker RPH | 500 | Worker당 시간당 최대 LLM 요청 수 |
| Global budget | configurable | 전체 Worker의 월간 비용 한도 |
| On limit reached | queue | 한도 초과 시 큐잉 (critical 태스크는 예외) |

### Offline Queuing

- 스케줄된 태스크는 계속 실행, LLM 필요 단계는 skip
- 결과는 SQLite 저장: `{task_id, result, timestamp, needs_llm}`
- **큐 크기 제한**: 최대 10,000행 또는 100MB. 초과 시 가장 오래된 non-critical 항목부터 제거
- 재연결 시 `sync` 메시지로 일괄 전송, `needs_llm: true` 항목은 Commander가 후처리

### Task Idempotency

태스크 재할당으로 인한 중복 실행 방지:
- 모든 태스크에 `idempotency_key` 부여
- Commander가 태스크 재할당 시 원본을 `reassigned` 상태로 마킹
- 원래 Worker가 뒤늦게 결과를 보고하면, Commander는 `reassigned` 상태를 확인 후 accept-first-wins 정책으로 처리
- 이미 성공 결과가 있으면 뒤늦은 결과는 감사 로그에만 기록

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
  "reactive_triggers": [
    {"source": "metrics_poll", "condition": "disk_usage > 90", "task": "disk_cleanup", "interval_seconds": 60},
    {"source": "file_watch", "path": "/var/log/syslog", "pattern": "OOM", "task": "oom_report"}
  ],
  "policies": {
    "auto_actions": ["restart_pod", "drain_node"],
    "require_approval": ["delete_pod", "cordon_node"],
    "blocked": ["delete_namespace", "reset_cluster"]
  },
  "escalation": {
    "on_failure_count": 3,
    "action": "notify_commander"
  },
  "limits": {
    "max_concurrent_long_running": 3,
    "max_llm_turns_per_task": 10
  }
}
```

### Reactive Task Event Sources

Worker가 로컬 이벤트를 감지하는 방식:

| Source | Mechanism | Use Case |
|--------|-----------|----------|
| `metrics_poll` | 주기적 시스템 메트릭 수집 (psutil) | CPU, 메모리, 디스크 임계값 |
| `file_watch` | inotify/fsevents 기반 파일 변경 감시 | 로그 패턴 매칭 |
| `process_watch` | 프로세스 상태 변경 감시 | 크래시 감지, 좀비 프로세스 |
| `systemd_journal` | journald 스트리밍 (Linux only) | 서비스 장애 감지 |

### Role Assignment Flow

1. 사용자 요청 또는 Commander 자동 추천
2. `role_update` 메시지로 Worker에 역할 정의 전달
3. Worker: Scheduler에 cron 등록, reactive trigger 활성화, 도구/정책 적용
4. 변경: 언제든 `role_update`로 추가·수정·제거 가능

### Task Types

| Type | Description | Example | Lifecycle |
|------|-------------|---------|-----------|
| `scheduled` | cron 기반 반복 | 1분마다 pod 상태 체크 | cron → 실행 → 보고 → 반복 |
| `on_demand` | Commander 즉시 요청 | nginx 로그 조회 | 할당 → 실행 → 보고 |
| `reactive` | 로컬 이벤트 트리거 | 디스크 90% 초과 시 정리 | 감지 → 실행 → 보고 |
| `long_running` | 지속 실행 | 로그 스트리밍, 파일 감시 | 시작 → 주기적 보고 → cancel 시 종료 |

**Long-running task management**: 역할당 최대 동시 실행 수 제한 (`max_concurrent_long_running`). 역할 변경 시 해당 역할의 long-running 태스크는 graceful cancel. 리소스 사용량은 heartbeat에 포함하여 보고.

### Escalation

- 동일 태스크 연속 3회 실패 → Commander 에스컬레이션
- Commander의 CoreAgent가 상위 판단
- 필요시 사용자 알림 (기존 메신저 채널)

## Security Model

### mTLS PKI

```
BreadMind Root CA (offline, 패스프레이즈 보호)
  └── Intermediate CA (online, Commander에서 운영)
        ├── Commander 서버 인증서
        ├── Worker 클라이언트 인증서 @k8s-node1
        ├── Worker 클라이언트 인증서 @pve-host1
        └── Worker 클라이언트 인증서 @openwrt-gw

Code Signing Key (CA와 별도, 패스프레이즈 보호)
  └── Worker 업데이트 패키지 서명
```

- **Root CA 키** — 오프라인 보관, 초기 설정 시 한 번만 사용하여 Intermediate CA 발급
- **Intermediate CA 키** — Commander의 암호화된 저장소, 기동 시 패스프레이즈 입력 필요 (또는 환경변수)
- **Code Signing Key** — CA 키와 물리적으로 분리, Worker 업데이트 서명 전용
- **인증서 수명** — Worker 인증서 90일, 만료 7일 전 Intermediate CA가 자동 갱신
- **폐기** — CRL 업데이트 후 Commander가 매 WebSocket 핸드셰이크 시 CRL 검증

### Message-Level Security

- mTLS 위에 추가로 **메시지 HMAC** (SHA-256) 적용
- 세션 키: mTLS 핸드셰이크에서 TLS exporter로 파생
- **seq**: 단조 증가 시퀀스 번호, 양측이 검증하여 replay attack 방지
- 비정상 seq 감지 시 연결 즉시 종료 + 감사 로그

### Permission Hierarchy

- Commander: full authority
- Worker: 역할 정의에 명시된 도구/정책만 실행 가능
- Worker 로컬 Safety Guard가 역할 범위 밖 tool_call 차단

### Threat Model

| Threat | Mitigation |
|--------|------------|
| Worker 인증서 탈취 | CRL 즉시 업데이트, Worker 강제 제거 |
| 악의적 LLM 응답 | Worker 로컬 Safety Guard blocked 정책 |
| Worker 노드 침해 | 역할 범위 제한으로 blast radius 최소화, 즉시 연결 해제 |
| 중간자 공격 | mTLS 양방향 인증 |
| Commander 침해 | Root CA 오프라인 분리, 감사 로그 외부 전송, Intermediate CA 폐기 가능 |
| 업데이트 채널 공격 | 코드 서명 검증 (별도 signing key) |
| 메시지 위조/재전송 | 메시지 HMAC + 시퀀스 번호 검증 |

### Audit Logging

- 모든 Worker 태스크/LLM 호출/도구 사용을 Commander에 기록
- 기존 audit_log 테이블에 `agent_id` 필드 추가
- `trace_id`로 Commander-Worker 간 요청 추적 가능

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

CREATE INDEX idx_agents_status ON agents(status);

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
    idempotency_key VARCHAR(128),
    type VARCHAR(20) NOT NULL,
    params JSONB,
    status VARCHAR(20) DEFAULT 'pending',
    result JSONB,
    metrics JSONB,
    trace_id UUID,
    created_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_agent_tasks_agent_status ON agent_tasks(agent_id, status);
CREATE INDEX idx_agent_tasks_created ON agent_tasks(created_at);
CREATE INDEX idx_agent_tasks_idempotency ON agent_tasks(idempotency_key);

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
ALTER TABLE audit_log ADD COLUMN trace_id UUID;
```

### Worker (SQLite) — Local Schema

```sql
CREATE TABLE offline_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    result JSON NOT NULL,
    needs_llm BOOLEAN DEFAULT 0,
    priority INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    synced_at TEXT
);

-- 큐 크기 제한: 최대 10,000행. 초과 시 priority 낮은 것부터 제거 (앱 레벨에서 관리)

CREATE TABLE task_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    idempotency_key TEXT,
    status TEXT NOT NULL,
    result JSON,
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

## Known Limitations & Future Extensions

- **Commander HA**: 현재 Commander는 단일 장애점. 향후 active-passive failover (공유 DB 기반) 고려
- **Worker-to-Worker 통신**: 현재 hub-and-spoke만. 향후 P2P mesh로 확장 가능
- **OpenWrt 경량 Worker**: Python 런타임이 무거울 수 있어 Go/Rust 기반 경량 바이너리 고려
- **Commander 연장 장애 시 Worker 자율성**: 현재는 기할당 태스크만 수행. 향후 로컬 LLM 폴백 고려
