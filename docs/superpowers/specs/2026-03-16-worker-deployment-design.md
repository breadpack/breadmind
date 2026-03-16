# Worker Agent Deployment System Design

**Date**: 2026-03-16
**Status**: Approved
**Supersedes**: `deploy/install/install-worker.sh`, `deploy/install/install-worker.ps1` (static scripts replaced by dynamic generation)

## Overview

Commander가 Worker를 안전하게 프로비저닝하기 위한 배포 시스템. Join Token 기반 인증으로 Worker가 등록하면 mTLS 인증서를 발급하고, 이후 모든 통신은 mTLS + HMAC으로 보호한다. 배포 방식은 SSH push와 one-liner install script 두 가지를 동등하게 지원한다.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Provisioning model | Commander-Centric | Commander가 토큰 생성, 스크립트 생성, 인증서 발급을 모두 중앙 관리 |
| Initial auth | Join Token → mTLS | 일회성 토큰으로 초기 신뢰 수립 후 PKI 기반 상호 인증으로 전환 |
| Deployment methods | SSH push + one-liner (동등 우선순위) | SSH 접근 가능하면 push, 불가하면 대상 노드에서 pull |
| Install scripts | Commander가 동적 생성 | 토큰/URL/설정이 내장된 스크립트를 요청 시 생성. 기존 정적 스크립트 대체 |
| UI interaction | Web UI form + chat command | 두 경로 모두 동일한 provisioning API 호출 |

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                    Commander                          │
│                                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │ TokenManager │  │ Script       │  │ SSH Push   │ │
│  │ (create,     │  │ Generator    │  │ Deployer   │ │
│  │  validate,   │  │ (Linux/macOS │  │ (asyncssh) │ │
│  │  expire,     │  │  /Windows)   │  │            │ │
│  │  revoke)     │  └──────┬───────┘  └─────┬──────┘ │
│  └──────┬───────┘         │                │         │
│         │          ┌──────┴────────────────┴───────┐ │
│         │          │    Worker Provisioning API     │ │
│         │          │    /api/workers/*              │ │
│         └──────────┤                               │ │
│                    └──────────┬─────────────────────┘ │
│  ┌─────────┐  ┌──────────┐   │   ┌────────────────┐  │
│  │ PKI     │  │ Agent    │   │   │ Monitoring     │  │
│  │ Manager │  │ Registry │◄──┘   │ Routes         │  │
│  └─────────┘  └──────────┘       └────────────────┘  │
└──────────────────────────────────────────────────────┘
         │ mTLS                    ▲ HTTPS (token-auth)
    ┌────▼─────┐              ┌────┴─────┐
    │ Worker   │              │ Target   │
    │ (joined) │              │ Node     │
    └──────────┘              │ (curl/   │
                              │  irm)    │
                              └──────────┘
```

## Components

### 1. JoinToken Model + TokenManager

**JoinToken 구조**:
- `id`: UUID — 토큰 식별자
- `secret`: 32-byte cryptographically random value (hex-encoded)
- `created_at`: 생성 시각
- `expires_at`: 만료 시각 (TTL 기반)
- `max_uses`: 최대 사용 횟수 (default: 1)
- `use_count`: 현재 사용 횟수
- `revoked`: 폐기 여부
- `metadata`: 생성 시 사용자 지정 라벨 (optional)

**TTL 정책**:
- Default: 1시간
- Maximum: 24시간
- 만료된 토큰은 주기적 정리 (1시간 간격)

**TokenManager 책임**:
- `create(ttl, max_uses, metadata)` — 토큰 생성, DB 저장
- `validate(token_id, secret)` — 유효성 검증 (만료, 사용횟수, 폐기 상태)
- `consume(token_id)` — use_count 증가, max_uses 도달 시 자동 만료
- `revoke(token_id)` — 즉시 폐기
- `list(include_expired)` — 토큰 목록 조회
- `cleanup()` — 만료/폐기 토큰 정리

### 2. Worker Provisioning API

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/workers/tokens` | POST | Session | Join Token 생성 |
| `/api/workers/tokens` | GET | Session | 토큰 목록 조회 |
| `/api/workers/tokens/{id}` | DELETE | Session | 토큰 폐기 |
| `/api/workers/install-script` | GET | Join Token | 동적 설치 스크립트 반환 (OS 자동 감지) |
| `/api/workers/register` | POST | Join Token | Worker 등록 (토큰 검증 → 인증서 발급) |
| `/api/workers/deploy/ssh` | POST | Session | SSH push 배포 실행 |
| `/api/workers` | GET | Session | Worker 목록 + 상태 |
| `/api/workers/{id}` | GET | Session | Worker 상세 정보 |
| `/api/workers/{id}` | DELETE | Session | Worker 제거 (decommission) |
| `/api/workers/{id}/metrics` | GET | Session | Worker 메트릭 (CPU, mem, disk) |
| `/api/workers/{id}/env` | GET | Session | Worker 환경 스캔 결과 |
| `/api/workers/{id}/tasks` | GET | Session | Worker 태스크 이력 |
| `/api/workers/{id}/logs` | GET | Session | Worker 로그 (tail) |

### 3. Dynamic Install Script Generator

Commander가 요청 시 설치 스크립트를 동적으로 생성한다. 스크립트에는 다음이 내장된다:
- Commander URL (WebSocket endpoint)
- Join Token (id + secret)
- 토큰 만료 시각 (스크립트 내 사전 검증용)

**생성 대상 플랫폼**:

| Platform | Script | Invocation |
|----------|--------|------------|
| Linux / macOS | Bash | `curl -sfL https://commander/api/workers/install-script?token=TOKEN \| bash` |
| Windows | PowerShell | `irm https://commander/api/workers/install-script?token=TOKEN \| iex` |

**스크립트 동작 흐름**:
1. 시스템 요구사항 확인 (Python 3.11+, 디스크 공간)
2. BreadMind Worker 패키지 다운로드 및 설치
3. 내장된 토큰으로 `/api/workers/register` 호출
4. 반환된 mTLS 인증서를 로컬에 저장
5. Worker 프로세스 시작 (systemd service / Windows service)
6. Commander로 WebSocket 연결, 초기 환경 보고

**보안**: install-script 엔드포인트는 유효한 Join Token이 있어야만 응답. HTTPS 필수.

### 4. SSH Push Deployer

기존 `shell_exec` 인프라의 asyncssh를 활용하여 대상 노드에 직접 배포한다.

**입력 파라미터**:
- `host`: 대상 호스트 (IP 또는 hostname)
- `port`: SSH 포트 (default: 22)
- `username`: SSH 사용자
- `auth_method`: password / key / agent
- `key_path`: SSH 키 경로 (key 인증 시)

**실행 흐름**:
1. SSH 연결 수립
2. 환경 스캔 (OS, arch, Python 버전, 디스크)
3. Join Token 자동 생성 (single-use, 10분 TTL)
4. 동적 설치 스크립트를 대상에 전송 및 실행
5. 설치 완료 대기 + Worker 등록 확인
6. 결과 반환 (성공/실패 + 로그)

**UI 지원**:
- Web UI: 배포 form (host, port, username, auth 입력)
- Chat command: `"worker deploy ssh user@host"` → intent classifier가 라우팅

### 5. Worker Registration Flow

```
Target Node                    Commander
    │                              │
    │ POST /api/workers/register   │
    │  {token_id, secret,          │
    │   hostname, os, arch, env}   │
    ├─────────────────────────────►│
    │                              │── TokenManager.validate()
    │                              │── TokenManager.consume()
    │                              │── PKIManager.issue_cert()
    │                              │── AgentRegistry.register()
    │                              │
    │  {agent_id, cert, key,       │
    │   ca_cert, ws_endpoint}      │
    │◄─────────────────────────────┤
    │                              │
    │ WSS connect (mTLS)           │
    ├─────────────────────────────►│
    │                              │── CRL check
    │                              │── Capability negotiation
    │  role_update                 │
    │◄─────────────────────────────┤
    │                              │
```

**등록 실패 시**: 토큰 use_count는 증가하지 않으므로 재시도 가능 (인증서 발급 전 실패 시).

### 6. Worker Monitoring

Commander는 등록된 Worker에 대해 다음 정보를 실시간 제공한다:

| Data | Source | Update Frequency |
|------|--------|-----------------|
| Worker list + status | AgentRegistry | 실시간 (WebSocket 이벤트) |
| System metrics (CPU, mem, disk) | Heartbeat | 30초 |
| Environment scan | env_scanner (초기 등록 시 + on-demand) | 요청 시 |
| Task history | agent_tasks 테이블 | 태스크 완료 시 |
| Logs | Worker → Commander streaming | 실시간 |

### 7. Chat Integration

기존 intent classifier에 Worker 관련 인텐트를 추가한다:

| Intent | Example | Action |
|--------|---------|--------|
| `worker_deploy_ssh` | "deploy worker to 192.168.1.10" | SSH push 배포 |
| `worker_create_token` | "create a join token" | 토큰 생성 + one-liner 출력 |
| `worker_list` | "show workers" | Worker 목록 |
| `worker_status` | "how is the k8s worker doing" | 특정 Worker 상태 |
| `worker_remove` | "remove worker pve-host1" | Decommission |

## Security Model

### Join Token Security

- Token secret은 32-byte cryptographically random (256-bit entropy)
- DB에는 secret의 SHA-256 해시만 저장 (원본은 생성 시 한 번만 노출)
- Token은 URL parameter로 전달되므로 HTTPS 필수
- Single-use 토큰: 한 번 사용 후 자동 만료
- Multi-use 토큰: max_uses까지 사용 가능 (batch provisioning용)
- 모든 토큰은 TTL 만료 자동 적용

### Token → mTLS 전환

1. Worker가 유효한 토큰으로 `/api/workers/register` 호출
2. Commander가 토큰 검증 후 Worker 전용 클라이언트 인증서 발급 (PKIManager)
3. 인증서 + CA cert를 Worker에 반환
4. 이후 모든 WebSocket 통신은 mTLS로 보호
5. Join Token은 더 이상 사용되지 않음 (인증서가 신원 증명)

### Install Script Endpoint Security

- 유효한 Join Token 없이는 404 반환 (스크립트 노출 방지)
- 스크립트 내 토큰은 등록 완료 후 무효화
- Rate limit: IP당 분당 10회

## Database Schema Additions

```sql
CREATE TABLE join_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    secret_hash VARCHAR(64) NOT NULL,
    ttl_seconds INTEGER NOT NULL DEFAULT 3600,
    expires_at TIMESTAMPTZ NOT NULL,
    max_uses INTEGER NOT NULL DEFAULT 1,
    use_count INTEGER NOT NULL DEFAULT 0,
    revoked BOOLEAN NOT NULL DEFAULT false,
    metadata JSONB,
    created_by UUID,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_join_tokens_expires ON join_tokens(expires_at);
CREATE INDEX idx_join_tokens_active ON join_tokens(revoked, expires_at);
```

## Existing Code Integration

| Module | Integration |
|--------|-------------|
| `network/worker.py` | 등록 시 Join Token 기반 초기 인증 추가 |
| `network/commander.py` | Provisioning API 라우트 마운트, SSH deployer 통합 |
| `network/pki.py` | 등록 플로우에서 호출 (토큰 검증 후 인증서 발급) |
| `network/registry.py` | Worker 등록/상태 관리에 토큰 메타데이터 연동 |
| `network/protocol.py` | 변경 없음 (기존 HMAC envelope 그대로 사용) |
| `core/env_scanner.py` | Worker 등록 시 + 모니터링 on-demand 호출 |
| `deploy/install/*` | 정적 스크립트 삭제, 동적 생성으로 대체 |

## Deployment Flow Summary

### Method A: SSH Push

```
User (UI form or chat) → Commander API → SSH connect to target
  → environment scan → auto-create token → push & run install script
  → Worker registers → cert issued → WebSocket connected → ready
```

### Method B: One-Liner Install

```
User (UI or chat) → Commander creates token → shows one-liner command
  → User runs on target node → script downloads, installs, registers
  → cert issued → WebSocket connected → ready
```

## Known Limitations

- Join Token은 URL parameter로 전달되므로 서버 access log에 노출될 수 있음. 프로덕션에서는 access log에서 토큰 파라미터를 마스킹하거나 POST body로 전환 고려.
- SSH push는 대상 노드에 SSH 접근이 가능해야 하며, 방화벽/NAT 환경에서는 one-liner 방식 사용.
- Multi-use 토큰은 편의성을 위해 제공하지만, 보안상 single-use를 권장.
