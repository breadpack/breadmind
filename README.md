# BreadMind

AI Infrastructure Agent — Kubernetes, Proxmox, OpenWrt를 자연어로 모니터링하고 관리하는 자율형 에이전트.

## Features

- **멀티 LLM 지원** — Claude, Gemini, Grok, Ollama, CLI 프로바이더 자동 전환 및 폴백 체인
- **인프라 자동 감지** — K8s 클러스터, Proxmox 하이퍼바이저, OpenWrt 라우터, Docker 자동 탐지
- **6개 메신저 연결** — Slack, Discord, Telegram, WhatsApp, Gmail, Signal 자동 연결 위자드
- **MCP 서버 통합** — Model Context Protocol 서버 자동 탐색 및 설치
- **스킬 시스템** — OS/도메인별 스킬 자동 등록 (패키지 관리, DB, 웹서버, 보안 등)
- **분산 에이전트 네트워크** — Commander/Worker 모드로 멀티 노드 관리
- **3계층 메모리** — Working / Episodic / Semantic 메모리 + Knowledge Graph
- **모니터링 엔진** — 룰 기반 이벤트 감지 + 자동 대응 (승인 플로우 포함)
- **웹 대시보드** — 실시간 채팅, 도구 브라우저, 설정, 모니터링 알림

## Quick Start

### 요구 사항

- Python 3.12+
- PostgreSQL 12+ (또는 Docker)
- LLM API 키 (Claude, Gemini 등) 또는 Ollama

### 설치

**원라인 설치 (Linux/macOS):**

```bash
curl -fsSL https://raw.githubusercontent.com/breadpack/breadmind/master/deploy/install/install.sh | bash
```

기존 PostgreSQL 사용 시:

```bash
curl -fsSL https://raw.githubusercontent.com/breadpack/breadmind/master/deploy/install/install.sh | bash -s -- --external-db
```

**pip 설치:**

```bash
pip install breadmind
```

전체 기능 설치:

```bash
pip install "breadmind[browser,messenger,container,embeddings]"
```

**소스에서 설치 (개발):**

```bash
git clone git@github.com:breadpack/breadmind.git
cd breadmind
pip install -e ".[dev,browser,messenger,container,embeddings]"
```

### Optional Dependencies

| 그룹 | 패키지 | 용도 |
|------|--------|------|
| `browser` | playwright | 웹 브라우저 자동화 |
| `messenger` | twilio, google-api | WhatsApp, Gmail 연동 |
| `container` | docker | Docker 컨테이너 격리 실행 |
| `embeddings` | sentence-transformers | 시맨틱 검색 임베딩 |

## 실행

### 웹 UI 모드 (권장)

```bash
breadmind --web
```

기본적으로 `http://localhost:8080`에서 대시보드에 접근할 수 있습니다.

```bash
# 호스트/포트 지정
breadmind --web --host 0.0.0.0 --port 9090

# 설정 디렉터리 지정
breadmind --web --config-dir /path/to/config

# 로그 레벨 지정
breadmind --web --log-level DEBUG
```

### 첫 실행 — 설정 위자드

처음 실행하면 설정 위자드가 자동으로 시작됩니다:

1. **LLM 프로바이더 선택** — Claude, Gemini(무료), Grok, Ollama(로컬) 중 선택
2. **API 키 입력** — 선택한 프로바이더의 API 키 입력 및 검증
3. **환경 자동 탐지** — Docker, Kubernetes, Proxmox, OpenWrt 자동 감지
4. **설정 완료** — 데이터베이스에 설정 저장

웹 UI에서는 `/api/setup/*` 엔드포인트를 통해 동일한 설정이 가능합니다.

## 설정

설정 파일 위치:

- **Linux/macOS**: `~/.config/breadmind/config.yaml`
- **Windows**: `%APPDATA%\breadmind\config.yaml`

### config.yaml

```yaml
llm:
  default_provider: claude        # claude | gemini | grok | ollama | cli
  default_model: claude-sonnet-4-6
  fallback_chain: [claude, ollama]  # 장애 시 자동 전환
  tool_call_max_turns: 10
  tool_call_timeout_seconds: 30

database:
  host: localhost
  port: 5432
  name: breadmind
  user: breadmind
  password: breadmind_dev

web:
  host: 127.0.0.1
  port: 8080

security:
  auth_enabled: false
  session_timeout: 86400

mcp:
  auto_discover: true
  max_restart_attempts: 3

network:
  mode: standalone   # standalone | commander | worker
```

### 환경 변수

```bash
# LLM API 키
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AI...
XAI_API_KEY=xai-...

# 데이터베이스
DB_HOST=localhost
DB_PORT=5432
DB_NAME=breadmind
DB_USER=breadmind
DB_PASSWORD=breadmind_dev

# 메신저 (선택)
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
DISCORD_BOT_TOKEN=...
TELEGRAM_BOT_TOKEN=...
```

환경 변수는 설정 디렉터리의 `.env` 파일에 저장할 수도 있습니다.

## LLM 프로바이더

| 프로바이더 | 모델 | 무료 | 설정 |
|-----------|------|------|------|
| **Claude** | claude-sonnet-4-6, claude-haiku-4-5 | - | [console.anthropic.com](https://console.anthropic.com) |
| **Gemini** | gemini-2.5-flash, gemini-2.5-pro | O | [aistudio.google.com](https://aistudio.google.com) |
| **Grok** | grok-3, grok-3-mini | - | [console.x.ai](https://console.x.ai) |
| **Ollama** | llama3.1, mistral, qwen2.5 | O (로컬) | [ollama.com](https://ollama.com) |
| **CLI** | claude -p (서브프로세스) | O | Claude CLI 설치 필요 |

폴백 체인 설정 시, 주 프로바이더 장애 시 자동으로 다음 프로바이더로 전환됩니다.

## 메신저 연결

BreadMind는 6개 메신저 플랫폼을 지원하며, 자동 연결 위자드를 제공합니다.

### 웹 UI에서 연결

Settings > Messengers에서 플랫폼을 선택하고 자동 가이드를 따릅니다.

### 채팅에서 연결

```
사용자: 텔레그램 연결해줘
BreadMind: 📋 telegram 연결 설정 (1/3)
           BotFather에서 봇 생성...
```

### CLI에서 연결

```bash
# 대화형 위자드
breadmind messenger setup

# 특정 플랫폼
breadmind messenger setup --platform slack

# 상태 확인
breadmind messenger status

# 재시작
breadmind messenger restart telegram
```

### 플랫폼별 자동화 수준

| 플랫폼 | 자동화 | 수동 단계 |
|--------|--------|----------|
| Telegram | 90% | BotFather 토큰 복사 1회 |
| Slack | 95% | OAuth "허용" 클릭 1회 |
| Discord | 60% | 봇 생성 + 토큰 복사 + 서버 초대 |
| WhatsApp | 70% | Twilio 계정 정보 복사 |
| Gmail | 80% | Google Cloud 설정 + OAuth 허용 |
| Signal | 75% | 전화번호 + SMS 인증 |

설정된 메신저는 **재시작 시 자동으로 연결**되며, 연결 끊김 시 **지수 백오프로 자동 재연결**됩니다 (최대 10회).

## 빌트인 도구

| 도구 | 설명 |
|------|------|
| `shell_exec` | 로컬/SSH/Docker 명령 실행 (보안 검증 포함) |
| `web_search` | DuckDuckGo 웹 검색 |
| `file_read` | 파일 읽기 |
| `file_write` | 파일 쓰기 |
| `messenger_connect` | 메신저 자동 연결 |
| `swarm_role` | 팀 역할 관리 |

추가로 MCP 서버를 통해 외부 도구를 무제한으로 확장할 수 있습니다.

## 스킬 시스템

BreadMind는 실행 환경을 자동 감지하여 적절한 스킬을 등록합니다.

### OS 스킬 (자동 감지)

- **Linux**: apt/dnf/apk 패키지 관리, systemctl, journalctl
- **macOS**: Homebrew, launchctl, system_profiler
- **Windows**: PowerShell, Get-Service, wmic

### 도메인 스킬 (소프트웨어 감지 시 자동 등록)

- **웹서버**: nginx, apache, caddy, traefik
- **데이터베이스**: MySQL, PostgreSQL, Redis, MongoDB
- **보안**: OpenSSL, certbot, ufw, firewalld, fail2ban
- **가상화**: Proxmox, KVM, VirtualBox
- **모니터링**: Prometheus, Grafana, Netdata
- **CI/CD**: Jenkins, GitLab Runner, GitHub CLI
- **스토리지**: ZFS, LVM, NFS, Samba
- **네트워크**: BIND, dnsmasq, WireGuard, HAProxy

## 분산 에이전트 네트워크

여러 서버에 BreadMind를 분산 배치하여 중앙 관리할 수 있습니다.

### Commander 모드 (중앙 허브)

```bash
breadmind --web --mode commander
```

- WebSocket 허브 (포트 8081)
- 워커 에이전트 등록 및 헬스체크
- 태스크 로드밸런싱 및 분배
- LLM 프록시 (워커당 30 RPM 레이트리밋)

### Worker 모드 (원격 에이전트)

```bash
breadmind --mode worker --commander-url wss://commander:8081/ws/agent/self
```

- 경량 런타임 (PostgreSQL/Docker 불필요)
- Commander로부터 태스크 수신 및 실행
- 오프라인 큐 지원 (최대 10,000건)
- 주기적 헬스체크 (CPU, 메모리, 디스크)

### 워커 원격 설치

Commander 웹 UI에서 워커 설치 스크립트를 생성하거나:

```bash
curl -fsSL https://commander:8080/api/workers/install-script | bash
```

## Docker 배포

### Docker Compose

```bash
cd docker
docker compose up -d
```

서비스 구성:
- **breadmind**: 메인 애플리케이션 (포트 8080)
- **postgres**: PostgreSQL + pgvector (포트 5432)

### Kubernetes (Helm)

```bash
cd deploy/helm
helm install breadmind ./breadmind \
  --set config.llm.defaultProvider=claude \
  --set secrets.anthropicApiKey=$ANTHROPIC_API_KEY
```

```yaml
# values.yaml 주요 설정
replicaCount: 1
image:
  repository: breadmind
  tag: "0.1.0"
service:
  type: ClusterIP
  port: 8080
postgres:
  enabled: true
  storage:
    size: 10Gi
resources:
  requests:
    memory: 256Mi
    cpu: 100m
  limits:
    memory: 512Mi
    cpu: 500m
```

## 모니터링

BreadMind는 연결된 인프라를 자동으로 모니터링합니다.

- **Kubernetes**: Pod CrashLoopBackOff, Node NotReady, 리소스 임계값
- **Proxmox**: VM 상태, 스토리지 사용량, 클러스터 쿼럼
- **OpenWrt**: 인터페이스 상태, 시스템 리소스

이벤트 발생 시 설정된 메신저로 알림을 보내고, 승인 플로우를 통해 자동 대응합니다.

## 보안

- **명령어 블랙리스트**: `rm -rf /`, `mkfs`, `dd if=`, fork bomb 등 위험 명령 차단
- **파일 보호**: `.env`, `credentials`, `*.key`, `*.pem` 등 민감 파일 접근 제한
- **경로 검증**: symlink 탈출 및 디렉터리 트래버설 방지
- **SSH 호스트 화이트리스트**: 허용된 호스트만 원격 실행
- **토큰 마스킹**: UI에서 토큰 표시 시 마스킹 처리
- **접근 로그**: 토큰 조회/수정/삭제 이력 기록
- **인증**: 웹 UI 패스워드 인증 (선택)

## 메모리 시스템

3계층 메모리 아키텍처:

| 계층 | 용도 | 저장소 |
|------|------|--------|
| **Working Memory** | 현재 대화 컨텍스트 | 인메모리 |
| **Episodic Memory** | 과거 상호작용 | PostgreSQL + 벡터 검색 |
| **Semantic Memory** | 지식 그래프 | Apache AGE (그래프 DB) |

자동 메모리 관리:
- **프로모션**: Working → Episodic → Semantic (10분 주기)
- **가비지 컬렉션**: 관련성 10% 미만 노트 제거 (1시간 주기)
- **컨텍스트 빌더**: 질의 시 벡터 + 그래프 검색으로 관련 메모리 자동 조합

## API

웹 UI 모드에서 RESTful API를 제공합니다.

### 주요 엔드포인트

```
# 설정
GET  /api/setup/status           # 초기 설정 상태
POST /api/setup/complete          # 설정 완료

# 채팅
POST /api/chat                    # 메시지 전송
WS   /ws                          # WebSocket 실시간 채팅

# 메신저
GET  /api/messenger/platforms     # 플랫폼 목록 및 상태
POST /api/messenger/{platform}/auto-connect  # 자동 연결 위자드
GET  /api/messenger/lifecycle/status         # 게이트웨이 상태
GET  /api/messenger/lifecycle/health         # 헬스 체크

# 도구
GET  /api/tools                   # 등록된 도구 목록

# 모니터링
GET  /api/monitoring/events       # 이벤트 목록
GET  /api/monitoring/rules        # 모니터링 규칙

# 보안
GET  /api/messenger/security/logs # 접근 로그
```

## 프로젝트 구조

```
src/breadmind/
├── core/           # 에이전트, 부트스트랩, 설정 위자드
├── llm/            # LLM 프로바이더 (Claude, Gemini, Grok, Ollama)
├── tools/          # 빌트인 도구, MCP 클라이언트, 브라우저
├── messenger/      # 6개 메신저 게이트웨이 + 자동 연결
├── monitoring/     # 모니터링 엔진, 룰, 루프 보호
├── memory/         # Working/Episodic/Semantic 메모리
├── skills/         # OS/도메인 스킬 자동 탐지
├── network/        # Commander/Worker 분산 네트워크
├── mcp/            # MCP 마켓플레이스 통합
├── storage/        # PostgreSQL, 설정 저장
├── web/            # FastAPI 앱, 라우트, WebSocket
├── cli/            # CLI 명령어
├── config.py       # 설정 로딩, 페르소나, 암호화
└── main.py         # 진입점
```

## License

Private Repository
