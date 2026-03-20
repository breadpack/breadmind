# BreadMind

AI Infrastructure Agent — Kubernetes, Proxmox, OpenWrt를 자연어로 모니터링하고 관리하는 자율형 에이전트.

## Features

- **멀티 LLM 지원** — Claude, Gemini, Grok, Ollama, CLI 프로바이더 자동 전환 및 폴백 체인
- **인프라 자동 감지** — K8s 클러스터, Proxmox 하이퍼바이저, OpenWrt 라우터, Docker 자동 탐지
- **6개 메신저 연결** — Slack, Discord, Telegram, WhatsApp, Gmail, Signal 자동 연결 위자드
- **MCP 서버 통합** — Model Context Protocol 서버 자동 탐색 및 설치
- **플러그인 시스템** — Claude Code 플러그인 호환, 마켓플레이스 검색/설치
- **코딩 에이전트 위임** — Claude Code, Codex, Gemini CLI에 코딩 작업 위임
- **스킬 시스템** — OS/도메인별 스킬 자동 등록 (패키지 관리, DB, 웹서버, 보안 등)
- **분산 에이전트 네트워크** — Commander/Worker 모드로 멀티 노드 관리
- **3계층 메모리** — Working / Episodic / Semantic 메모리 + Knowledge Graph
- **모니터링 엔진** — 룰 기반 이벤트 감지 + 자동 대응 (승인 플로우 포함)
- **웹 대시보드** — 실시간 채팅, Plugin Store, MCP Store, Skill Store, 모니터링

## Quick Start

### 요구 사항

- Python 3.12+
- PostgreSQL 12+ (pgvector 확장)
- LLM API 키 (Claude, Gemini 등) 또는 Ollama
- Redis (선택 — Celery 백그라운드 작업용)

### 원라인 설치 (권장)

**Linux/macOS:**

```bash
curl -fsSL https://raw.githubusercontent.com/breadpack/breadmind/master/deploy/install/install.sh | bash
```

이 스크립트가 자동으로 수행하는 작업:
- Python 3.12+ 확인/설치
- Docker 확인/설치
- PostgreSQL + pgvector Docker 컨테이너 시작
- BreadMind pip 설치
- 설정 파일 생성 (`~/.config/breadmind/config.yaml`)
- systemd 서비스 등록 (Linux)

기존 PostgreSQL 사용 시:

```bash
curl -fsSL https://raw.githubusercontent.com/breadpack/breadmind/master/deploy/install/install.sh | bash -s -- --external-db
```

**Windows:**

```powershell
irm https://raw.githubusercontent.com/breadpack/breadmind/master/deploy/install/install.ps1 | iex
```

### pip 설치 (수동)

BreadMind만 설치 (백엔드 서비스는 별도 구성 필요):

```bash
pip install git+https://github.com/breadpack/breadmind.git
```

전체 기능 설치:

```bash
pip install "breadmind[browser,messenger,container,embeddings] @ git+https://github.com/breadpack/breadmind.git"
```

특정 버전 설치:

```bash
pip install git+https://github.com/breadpack/breadmind.git@v0.3.0
```

### 소스에서 설치 (개발)

```bash
git clone https://github.com/breadpack/breadmind.git
cd breadmind
pip install -e ".[dev,browser,messenger,container,embeddings]"
```

## 백엔드 서비스 설치

pip 설치 시 PostgreSQL과 Redis는 포함되지 않습니다. 아래 방법 중 하나를 선택하세요.

### 방법 1: Docker Compose (권장)

PostgreSQL만 필요한 경우:

```bash
docker compose up -d postgres
```

BreadMind + PostgreSQL 전체 Docker 실행:

```bash
docker compose --profile full up -d
```

### 방법 2: Docker 개별 실행

**PostgreSQL + pgvector:**

```bash
docker run -d \
  --name breadmind-postgres \
  --restart unless-stopped \
  -e POSTGRES_DB=breadmind \
  -e POSTGRES_USER=breadmind \
  -e POSTGRES_PASSWORD=breadmind_dev \
  -p 5432:5432 \
  -v breadmind-pgdata:/var/lib/postgresql/data \
  pgvector/pgvector:pg17
```

**Redis (선택):**

```bash
docker run -d \
  --name breadmind-redis \
  --restart unless-stopped \
  -p 6379:6379 \
  redis:7-alpine
```

### 방법 3: 시스템 패키지 직접 설치

**Ubuntu/Debian:**

```bash
# PostgreSQL + pgvector
sudo apt-get update
sudo apt-get install -y postgresql postgresql-17-pgvector
sudo -u postgres createuser breadmind
sudo -u postgres createdb -O breadmind breadmind

# Redis (선택)
sudo apt-get install -y redis-server
```

**macOS (Homebrew):**

```bash
# PostgreSQL + pgvector
brew install postgresql@17 pgvector
brew services start postgresql@17
createuser breadmind
createdb -O breadmind breadmind

# Redis (선택)
brew install redis
brew services start redis
```

**Windows:**

```powershell
# PostgreSQL: https://www.postgresql.org/download/windows/ 에서 설치
# 설치 시 pgvector 확장 포함 선택

# 또는 winget으로:
winget install PostgreSQL.PostgreSQL.17

# Redis: WSL 또는 Memurai (Windows Redis 대안) 사용
```

### 데이터베이스 초기화

PostgreSQL 설치 후 pgvector와 Apache AGE 확장을 활성화합니다:

```sql
-- psql -U breadmind -d breadmind
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS age;
```

BreadMind은 첫 실행 시 필요한 테이블을 자동으로 생성합니다.

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
breadmind web
```

기본적으로 `http://localhost:8080`에서 대시보드에 접근할 수 있습니다.

```bash
# 호스트/포트 지정
breadmind web --host 0.0.0.0 --port 9090

# 설정 디렉터리 지정
breadmind web --config-dir /path/to/config

# 로그 레벨 지정
breadmind web --log-level DEBUG
```

### 첫 실행 — 설정 위자드

처음 실행하면 설정 위자드가 자동으로 시작됩니다:

1. **LLM 프로바이더 선택** — Claude, Gemini(무료), Grok, Ollama(로컬) 중 선택
2. **API 키 입력** — 선택한 프로바이더의 API 키 입력 및 검증
3. **환경 자동 탐지** — Docker, Kubernetes, Proxmox, OpenWrt 자동 감지
4. **설정 완료** — 데이터베이스에 설정 저장

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

## 플러그인 시스템

BreadMind는 Claude Code 플러그인 포맷과 호환되는 플러그인 시스템을 제공합니다.

### 플러그인 설치

```bash
# 마켓플레이스에서 검색/설치
breadmind plugin search aider
breadmind plugin install https://github.com/breadmind-plugins/aider-adapter

# 로컬 플러그인 설치
breadmind plugin install ./my-plugin

# Claude Code 플러그인 그대로 사용
breadmind plugin install ~/.claude/plugins/superpowers
```

### 플러그인 관리

```bash
breadmind plugin list                # 설치된 플러그인 목록
breadmind plugin enable <name>       # 활성화
breadmind plugin disable <name>      # 비활성화
breadmind plugin uninstall <name>    # 제거
```

### 플러그인 개발

BreadMind 플러그인은 Claude Code `plugin.json` 포맷을 사용합니다:

```
my-plugin/
├── .claude-plugin/
│   └── plugin.json        # 매니페스트
├── commands/              # 슬래시 커맨드
├── skills/                # 프롬프트 스킬
├── agents/                # 서브에이전트
└── hooks/                 # 이벤트 훅
```

BreadMind 전용 확장은 `x-breadmind` 네임스페이스 사용:

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "x-breadmind": {
    "coding_agents": [{"name": "aider", "cli_command": "aider", "prompt_flag": "--message"}],
    "roles": ["roles/expert.j2"]
  }
}
```

## 코딩 에이전트 위임

BreadMind가 외부 코딩 에이전트에 작업을 위임할 수 있습니다.

지원 에이전트: **Claude Code**, **Codex**, **Gemini CLI**

채팅에서 코딩 요청을 하면 자동으로 `code_delegate` 도구를 사용합니다:

```
사용자: breadmind 프로젝트에서 로그인 기능 추가해줘
BreadMind: [claude] code_delegate 실행 → 결과 보고
```

세션 관리로 이전 작업을 이어갈 수 있습니다.

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

### 플랫폼별 자동화 수준

| 플랫폼 | 자동화 | 수동 단계 |
|--------|--------|----------|
| Telegram | 90% | BotFather 토큰 복사 1회 |
| Slack | 95% | OAuth "허용" 클릭 1회 |
| Discord | 60% | 봇 생성 + 토큰 복사 + 서버 초대 |
| WhatsApp | 70% | Twilio 계정 정보 복사 |
| Gmail | 80% | Google Cloud 설정 + OAuth 허용 |
| Signal | 75% | 전화번호 + SMS 인증 |

설정된 메신저는 재시작 시 자동으로 연결되며, 연결 끊김 시 지수 백오프로 자동 재연결됩니다.

## Docker 배포

### 권장: PostgreSQL만 Docker + BreadMind은 호스트 실행

BreadMind는 인프라 관리 에이전트이므로 호스트의 kubectl, ssh, docker 등 CLI 도구에 직접 접근해야 합니다. **BreadMind 자체를 Docker 컨테이너에서 실행하면 호스트 환경에 접근할 수 없어 대부분의 기능이 제한됩니다.**

```bash
# 1. PostgreSQL만 Docker로 실행
docker compose up -d postgres

# 2. BreadMind은 호스트에서 실행
breadmind web
```

### 전체 Docker 실행 (제한적)

호스트 접근이 필요 없는 환경(테스트, 데모 등)에서만 사용:

```bash
docker compose --profile full up -d
```

> **주의:** Docker 컨테이너 내에서 BreadMind을 실행하면 shell_exec, kubectl, ssh, router_manage 등 호스트 의존 도구가 작동하지 않습니다.

### Kubernetes (Helm)

```bash
cd deploy/helm
helm install breadmind ./breadmind \
  --set config.llm.defaultProvider=claude \
  --set secrets.anthropicApiKey=$ANTHROPIC_API_KEY
```

> Kubernetes 배포 시 BreadMind Pod에 호스트 도구 접근이 필요하면 `hostPID`, `hostNetwork`, 볼륨 마운트 등의 설정이 필요합니다.

## 분산 에이전트 네트워크

여러 서버에 BreadMind를 분산 배치하여 중앙 관리할 수 있습니다.

### Commander 모드 (중앙 허브)

```bash
breadmind web --mode commander
```

### Worker 모드 (원격 에이전트)

```bash
breadmind web --mode worker --commander-url wss://commander:8081/ws/agent/self
```

- 경량 런타임 (PostgreSQL/Docker 불필요)
- Commander로부터 태스크 수신 및 실행
- 오프라인 큐 지원 (최대 10,000건)

## 업데이트

### 웹 UI에서

Settings > System에서 "Update Now" 버튼 클릭. 자동으로 최신 버전을 설치합니다.

### CLI에서

```bash
# GitHub Release에서 최신 버전 설치
pip install --upgrade --force-reinstall "breadmind @ git+https://github.com/breadpack/breadmind.git"

# 특정 버전 설치
pip install --upgrade --force-reinstall "breadmind @ git+https://github.com/breadpack/breadmind.git@v0.3.0"

# 개발 환경 (git clone 설치)
cd breadmind && git pull
```

### 버전 확인

```bash
breadmind version
```

## 보안

- **명령어 블랙리스트**: `rm -rf /`, `mkfs`, `dd if=`, fork bomb 등 위험 명령 차단
- **파일 보호**: `.env`, `credentials`, `*.key`, `*.pem` 등 민감 파일 접근 제한
- **경로 검증**: symlink 탈출 및 디렉터리 트래버설 방지
- **SSH 호스트 화이트리스트**: 허용된 호스트만 원격 실행
- **토큰 마스킹**: UI에서 토큰 표시 시 마스킹 처리
- **인증**: 웹 UI 패스워드 인증 (선택)

## 프로젝트 구조

```
src/breadmind/
├── core/           # 에이전트, 부트스트랩, 프롬프트 빌더
├── llm/            # LLM 프로바이더 (Claude, Gemini, Grok, Ollama)
├── prompts/        # Jinja2 프롬프트 템플릿 시스템
├── plugins/        # 플러그인 시스템 (Claude Code 호환)
├── coding/         # 코딩 에이전트 위임 (code_delegate)
├── tools/          # 빌트인 도구, MCP 클라이언트
├── messenger/      # 6개 메신저 게이트웨이 + 자동 연결
├── monitoring/     # 모니터링 엔진, 룰, 루프 보호
├── memory/         # Working/Episodic/Semantic 메모리
├── skills/         # OS/도메인 스킬 자동 탐지
├── network/        # Commander/Worker 분산 네트워크
├── mcp/            # MCP 마켓플레이스 통합
├── storage/        # PostgreSQL, 설정 저장
├── web/            # FastAPI 앱, 라우트, WebSocket
├── config.py       # 설정 로딩
└── main.py         # 진입점
```

## License

Private Repository
