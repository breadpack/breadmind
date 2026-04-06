# BreadMind Web Menu Redesign

## Overview

상단 탭 기반 네비게이션을 좌측 사이드바 기반으로 전환하고, 기능 그룹핑을 사용자 관점에서 재설계하여 3클릭 이내 모든 기능에 접근 가능하도록 개선한다.

## 핵심 결정 사항

- **상단 탭 → 좌측 사이드바**: 7개 상단 탭 제거, 좌측 사이드바로 전환
- **Store 통합**: MCP Store + Skill Store + Plugin Store → 단일 "Explore" 섹션
- **Settings 경량화**: Settings에 몰려있던 Monitoring/Automation/Connections를 독립 메뉴로 승격
- **사이드바 접힘**: 아이콘 전용 모드 지원 (56px), 펼침 모드 (240px)
- **Agents 서브탭 분해**: Scheduler/Swarm/Container/Webhook → Automation 섹션으로 이동

## 레퍼런스

- **n8n**: Workflows · Credentials · Executions (실행이력 독립 메뉴)
- **Windmill**: Scripts · Flows · Runs · Schedules · Resources (리소스 분리)
- **Home Assistant**: 사이드바 + 하단 유틸리티 분리 + Settings 서브 그리드
- **Dify.ai**: Studio · Explore · Knowledge · Tools · Plugins (AI 에이전트 중심)
- **Grafana**: 3단계 사이드바 계층 + 메가메뉴 + role-based visibility

---

## 레이아웃 변경

### Before (현재)

```
┌─────────────────────────────────────────────────┐
│  Header (BreadMind 로고 + 상태)                  │
├─────────────────────────────────────────────────┤
│  Tabs: Chat | Monitoring | MCP | Skill | Plugin | 비서 | Settings │
├─────────────────────────────────────────────────┤
│                                                 │
│              Tab Content (flex:1)                │
│                                                 │
└─────────────────────────────────────────────────┘
```

### After (재설계)

```
┌──────┬──────────────────────────────────────────┐
│      │  Header (페이지 제목 + 검색 + 알림)       │
│ Side ├──────────────────────────────────────────┤
│ bar  │                                          │
│      │              Page Content                │
│ 240px│                (flex:1)                   │
│ or   │                                          │
│ 56px │                                          │
│      │                                          │
├──────┴──────────────────────────────────────────┤
```

### HTML 구조 변경

```html
<!-- Before -->
<body>
  <header>...</header>
  <div class="tabs">...</div>
  <div class="main">
    <div class="tab-content" id="tab-chat">...</div>
    <div class="tab-content" id="tab-monitoring">...</div>
    ...
  </div>
</body>

<!-- After -->
<body>
  <div id="aurora-bg"></div>
  <div class="app-layout">
    <nav class="app-sidebar" id="app-sidebar">
      <div class="sidebar-header">...</div>
      <div class="sidebar-nav">...</div>
      <div class="sidebar-footer">...</div>
    </nav>
    <div class="app-main">
      <header class="app-header" id="app-header">...</header>
      <div class="app-content">
        <div class="page" id="page-chat">...</div>
        <div class="page" id="page-assistant">...</div>
        ...
      </div>
    </div>
  </div>
</body>
```

---

## 사이드바 메뉴 구조

### 주요 영역 (Primary Navigation)

```
┌──────────────────────────┐
│  🍞 BreadMind       [◀]  │  로고 + 사이드바 접기 토글
│                          │
│  MAIN                    │  카테고리 헤더
│  💬 Chat                 │  핵심 대화 인터페이스
│  📋 Assistant            │  할일 · 일정 · 연락처
│  ⚡ Automation           │  Webhook · 스케줄러 · Swarm · Jobs
│  📊 Monitoring           │  이벤트 · 성능 · 감사로그
│  🏪 Explore              │  MCP · Skills · Plugins 통합 마켓
│  🔌 Connections          │  Messenger · 서비스 통합 · 인프라
│                          │
│  ─────────────────────── │  구분선
│  SYSTEM                  │  카테고리 헤더
│  ⚙️ Settings             │  에이전트 · 보안 · 시스템 설정
│  👤 Profile              │  사용자 정보
│                          │
│  v2.1.0    🔔 3          │  버전 + 알림 배지
└──────────────────────────┘
```

### 접힘 모드 (Collapsed, 56px)

```
┌──────┐
│  🍞  │
│      │
│  💬  │
│  📋  │
│  ⚡  │
│  📊  │
│  🏪  │
│  🔌  │
│  ──  │
│  ⚙️  │
│  👤  │
│  🔔  │
└──────┘
```

호버 시 툴팁으로 메뉴 이름 표시.

---

## 각 메뉴 상세 설계

### 1. Chat (💬)

**변경사항**: 기존 Chat 탭과 거의 동일. 좌측 사이드바가 앱 사이드바로 대체되므로, Chat 내부의 세션/도구 사이드바는 Chat 페이지 내부에 유지.

**페이지 구성**:
```
┌──────────────────────────────────────────┐
│  Sessions [Clear] [+ New]      Tools ▾   │  Chat 내부 헤더
├────────────┬─────────────────────────────┤
│ Session 1  │  [메시지 영역]              │
│ Session 2  │                             │
│ Session 3  │                             │
│            │                             │
│ 📋 오늘    │  [입력 영역]                │
│ - Task 1   │                             │
│ - Event 1  │  Session: default           │
├────────────┴─────────────────────────────┤
```

### 2. Assistant (📋)

**변경사항**: 기존 "비서" 탭 그대로 이동. 이름을 "Assistant"로 통일.

**페이지 구성**: 기존 Personal 탭과 동일
- 서브탭: 📋 할 일 | 📅 일정 | 📇 연락처
- Kanban 보드 (할일)
- 타임라인 (일정)
- 카드 그리드 (연락처)
- [+ 추가] 플로팅 버튼

### 3. Automation (⚡)

**변경사항**: Settings > Agents에 묻혀있던 기능들을 독립 섹션으로 승격. Webhook도 여기로.

**서브탭 구성** (페이지 내 상단 탭):

```
[Webhooks] [Scheduler] [Swarm] [Jobs] [Containers]
```

#### 3-1. Webhooks
기존 Settings > Webhook 그대로 이동.
- Rules 탭: 규칙 CRUD + Dry-run 테스트
- Pipelines 탭: 파이프라인 CRUD + 액션 에디터
- YAML 탭: Import/Export
- **추가**: Webhook Endpoints 관리 (현재 Settings > Agents에 있던 것)

#### 3-2. Scheduler
기존 Settings > Agents > Scheduler 이동.
- Cron Jobs 목록 + 추가/삭제
- Heartbeat Tasks 목록 + 추가/삭제
- 실행 이력 (향후)

#### 3-3. Swarm
기존 Settings > Agents > Agent Swarms 이동.
- Swarm 실행/목록/상태
- Sub-agent 실행
- 역할(Roles) 관리는 Settings > Prompts에 유지

#### 3-4. Jobs
**신규 UI**: Background Jobs + Coding Jobs 통합 모니터링.
- Coding Jobs (기존 Monitoring 탭의 상단 영역)
- Background Jobs (API만 존재했던 기능에 UI 추가)
- 상태 필터: All | Running | Completed | Failed

#### 3-5. Containers
기존 Settings > Agents > Container Isolation 이동.
- Docker 상태
- 실행 중 컨테이너 목록
- 명령 실행 폼

### 4. Monitoring (📊)

**변경사항**: Coding Jobs를 Automation > Jobs로 이동. 대신 감사로그, 토큰 사용량, 도구 메트릭 등 옵저빌리티 기능을 여기로 통합.

**서브탭 구성**:

```
[Events] [Audit Log] [Usage] [Tool Metrics] [Approvals]
```

#### 4-1. Events
기존 Monitoring 탭의 이벤트 섹션 (Stats + 필터 + 이벤트 목록).

#### 4-2. Audit Log
기존 Settings > General > Recent Audit Log 이동 + 확장.
- 전체 감사로그 목록 (현재는 최근 항목만)
- 필터/검색 기능

#### 4-3. Usage
기존 Settings > General > Token Usage 이동.
- Input/Output/Cache 토큰
- 비용 추적
- 시간대별 사용량 (향후)

#### 4-4. Tool Metrics
기존 Settings > General > Tool Metrics 이동.
- 도구별 호출 수/성공률/평균 시간

#### 4-5. Approvals
기존 Settings > Safety > Pending Approvals 이동.
- 도구 실행 승인/거부 대기열
- 실시간 승인 카드

### 5. Explore (🏪)

**변경사항**: MCP Store + Skill Store + Plugin Store 3개를 하나의 마켓플레이스로 통합.

**서브탭 구성**:

```
[MCP Servers] [Skills] [Plugins]
```

각 탭의 UI는 기존 개별 Store 탭의 UI를 그대로 유지하되, 하나의 페이지 안에서 탭 전환.

#### 5-1. MCP Servers
기존 MCP Store 탭 그대로.
- 검색 + 소스 필터 (Verified / ClawHub)
- 카테고리 + 서버 카드
- Install Assistant 패널

#### 5-2. Skills
기존 Skill Store 탭 그대로.
- 검색 + 카테고리
- 스킬 카드 + 상세 패널

#### 5-3. Plugins
기존 Plugin Store 탭 그대로.
- 검색 + Browse/Installed 토글
- 카테고리 + 플러그인 카드
- 상세 사이드 패널

### 6. Connections (🔌)

**변경사항**: Settings > Messenger + Settings > Integrations + Infrastructure 를 통합.

**서브탭 구성**:

```
[Integrations] [Messenger] [Infrastructure] [Workers]
```

#### 6-1. Integrations
기존 Settings > Integrations 그대로 이동.
- 서비스 카테고리 (생산성/파일/연락처/메신저)
- 연결/해제 카드
- OAuth 플로

#### 6-2. Messenger
기존 Settings > Messenger 이동.
- 플랫폼 연결 상태
- 자동 연결 위저드
- 보안 설정

#### 6-3. Infrastructure
**신규 UI**: API만 존재했던 인프라 관리에 UI 추가.
- 네트워크 스캔 (Proxmox, K8s, Synology, OpenWRT, SSH)
- 연결된 인프라 목록
- 상태 서머리

#### 6-4. Workers
**신규 UI**: Commander/Worker 아키텍처 관리.
- 등록된 Worker 목록
- Join Token 발급/관리
- Worker 상태 모니터링

### 7. Settings (⚙️)

**변경사항**: 대폭 경량화. Monitoring, Automation, Connections로 분산된 항목을 제거하고, 순수 설정만 남김.

**서브탭 구성**:

```
[General] [Prompts] [Safety] [System]
```

#### 7-1. General
- Agent Persona (이름, 성격, 언어, 전문분야)
- API Keys (Anthropic, Gemini, OpenAI)
- LLM Provider (프로바이더/모델/max_turns/timeout)
- MCP Configuration (auto_discover, max_restart)
- Skill Markets & Registries

#### 7-2. Prompts
기존 그대로 유지.
- Main System Prompt
- Behavior Rules
- Swarm Role Prompts
- Swarm Coordinator Prompts
- MCP Install Assistant Prompt

#### 7-3. Safety
- Safety Rules (Blacklist, Approval List, User Permissions)
- Monitoring Rules (규칙 에디터 + Loop Protector)
- Tool Security (위험 패턴, SSH 호스트, 기본 디렉토리)

#### 7-4. System
- Agent Timeouts
- Memory (max_messages, session_timeout)
- Embedding Model
- Logging Level
- System Info + 업데이트 체크
- Database 정보
- Backup / Restore
- Danger Zone (삭제)

### 8. Profile (👤)

**신규**: 사이드바 하단에 사용자 프로필 영역.
- 로그인 상태 표시
- 로그아웃 버튼
- (향후) 개인 설정

---

## 기능 이동 매핑표

| 기존 위치 | 새 위치 | 비고 |
|-----------|---------|------|
| Tab: Chat | Chat | 동일 |
| Tab: Monitoring > Coding Jobs | Automation > Jobs | 이동 |
| Tab: Monitoring > Events | Monitoring > Events | 동일 |
| Tab: MCP Store | Explore > MCP Servers | 통합 |
| Tab: Skill Store | Explore > Skills | 통합 |
| Tab: Plugin Store | Explore > Plugins | 통합 |
| Tab: 비서 | Assistant | 이름 변경 |
| Settings > General > Agent Persona | Settings > General | 유지 |
| Settings > General > Token Usage | Monitoring > Usage | 이동 |
| Settings > General > Audit Log | Monitoring > Audit Log | 이동 |
| Settings > General > Tool Metrics | Monitoring > Tool Metrics | 이동 |
| Settings > General > API Keys | Settings > General | 유지 |
| Settings > General > LLM Provider | Settings > General | 유지 |
| Settings > General > Timeouts | Settings > System | 이동 |
| Settings > General > Memory | Settings > System | 이동 |
| Settings > General > MCP Config | Settings > General | 유지 |
| Settings > General > Skill Markets | Settings > General | 유지 |
| Settings > Prompts | Settings > Prompts | 유지 |
| Settings > Safety > Pending Approvals | Monitoring > Approvals | 이동 |
| Settings > Safety > Safety Rules | Settings > Safety | 유지 |
| Settings > Safety > Monitoring Rules | Settings > Safety | 유지 |
| Settings > Safety > Tool Security | Settings > Safety | 유지 |
| Settings > Messenger | Connections > Messenger | 이동 |
| Settings > Agents > Scheduler | Automation > Scheduler | 이동 |
| Settings > Agents > Sub-agents | Automation > Swarm | 통합 |
| Settings > Agents > Swarm | Automation > Swarm | 이동 |
| Settings > Agents > Container | Automation > Containers | 이동 |
| Settings > Agents > Webhooks (endpoints) | Automation > Webhooks | 이동 |
| Settings > System | Settings > System | 유지 |
| Settings > Integrations | Connections > Integrations | 이동 |
| Settings > Webhook (automation) | Automation > Webhooks | 이동 |
| (API only) Background Jobs | Automation > Jobs | 신규 UI |
| (API only) Infrastructure | Connections > Infrastructure | 신규 UI |
| (API only) Workers | Connections > Workers | 신규 UI |
| (API only) File Upload | (향후) | 범위 외 |

---

## 사이드바 컴포넌트 설계

### CSS 변수 추가

```css
:root {
    --sidebar-width: 240px;
    --sidebar-width-collapsed: 56px;
    --sidebar-bg: rgba(15, 20, 35, 0.95);
    --sidebar-border: rgba(255, 255, 255, 0.06);
    --sidebar-item-height: 38px;
    --sidebar-item-radius: 8px;
    --sidebar-icon-size: 18px;
    --header-height: 52px;
}
```

### 사이드바 HTML

```html
<nav class="app-sidebar" id="app-sidebar">
  <!-- 헤더: 로고 + 접기 -->
  <div class="sidebar-header">
    <span class="sidebar-logo">🍞</span>
    <span class="sidebar-brand">BreadMind</span>
    <button class="sidebar-toggle" onclick="toggleSidebar()">◀</button>
  </div>

  <!-- 주요 네비게이션 -->
  <div class="sidebar-nav">
    <div class="sidebar-group">
      <div class="sidebar-group-label">MAIN</div>
      <a class="sidebar-item active" data-page="chat">
        <span class="sidebar-icon">💬</span>
        <span class="sidebar-label">Chat</span>
      </a>
      <a class="sidebar-item" data-page="assistant">
        <span class="sidebar-icon">📋</span>
        <span class="sidebar-label">Assistant</span>
      </a>
      <a class="sidebar-item" data-page="automation">
        <span class="sidebar-icon">⚡</span>
        <span class="sidebar-label">Automation</span>
      </a>
      <a class="sidebar-item" data-page="monitoring">
        <span class="sidebar-icon">📊</span>
        <span class="sidebar-label">Monitoring</span>
        <span class="sidebar-badge" id="monitoring-badge"></span>
      </a>
      <a class="sidebar-item" data-page="explore">
        <span class="sidebar-icon">🏪</span>
        <span class="sidebar-label">Explore</span>
      </a>
      <a class="sidebar-item" data-page="connections">
        <span class="sidebar-icon">🔌</span>
        <span class="sidebar-label">Connections</span>
      </a>
    </div>

    <div class="sidebar-divider"></div>

    <div class="sidebar-group">
      <div class="sidebar-group-label">SYSTEM</div>
      <a class="sidebar-item" data-page="settings">
        <span class="sidebar-icon">⚙️</span>
        <span class="sidebar-label">Settings</span>
      </a>
    </div>
  </div>

  <!-- 하단: 프로필 + 버전 -->
  <div class="sidebar-footer">
    <div class="sidebar-divider"></div>
    <a class="sidebar-item" onclick="toggleProfile()">
      <span class="sidebar-icon">👤</span>
      <span class="sidebar-label">Profile</span>
    </a>
    <div class="sidebar-version">
      <span class="sidebar-label">v2.1.0</span>
      <span class="sidebar-badge-bell" id="notification-badge">🔔</span>
    </div>
  </div>
</nav>
```

### 페이지 전환 (switchPage)

기존 `switchTab(name)` → `switchPage(name)` 으로 교체.

```javascript
function switchPage(name) {
    // 사이드바 active 표시
    document.querySelectorAll('.sidebar-item').forEach(item => {
        item.classList.toggle('active', item.dataset.page === name);
    });
    // 페이지 표시 전환
    document.querySelectorAll('.page').forEach(p => {
        p.style.display = 'none';
    });
    const page = document.getElementById('page-' + name);
    if (page) {
        page.style.display = 'flex';
    }
    // 초기화 콜백
    const inits = {
        settings: loadSettings,
        monitoring: loadMonitoringPage,
        explore: loadExplorePage,
        assistant: initPersonalTab,
        automation: initAutomationPage,
        connections: initConnectionsPage,
    };
    if (inits[name]) inits[name]();
    // URL hash 업데이트
    location.hash = name;
}
```

---

## 서브탭 패턴 (통일)

Automation, Monitoring, Explore, Connections, Settings 내부에서 사용하는 서브탭 패턴을 통일.

```html
<div class="page-tabs">
  <button class="page-tab active" data-subtab="webhooks">Webhooks</button>
  <button class="page-tab" data-subtab="scheduler">Scheduler</button>
  <button class="page-tab" data-subtab="swarm">Swarm</button>
  <button class="page-tab" data-subtab="jobs">Jobs</button>
  <button class="page-tab" data-subtab="containers">Containers</button>
</div>
<div class="page-panel" id="subtab-webhooks">...</div>
<div class="page-panel" id="subtab-scheduler" style="display:none">...</div>
```

기존 Settings의 `switchSettingsTab()` 패턴을 일반화하여 재사용.

---

## 반응형 동작

| 화면 폭 | 사이드바 | 동작 |
|---------|---------|------|
| > 1200px | 펼침 (240px) 기본 | 토글로 접기 가능 |
| 768-1200px | 접힘 (56px) 기본 | 호버로 임시 펼침 |
| < 768px | 숨김 (0px) | 햄버거 메뉴로 오버레이 |

---

## 구현 범위

### Phase 1 (이번 구현)
- [x] 사이드바 HTML/CSS/JS 구현
- [x] 기존 탭 → 페이지 전환 마이그레이션
- [x] Store 3개 → Explore 통합
- [x] Settings 경량화 (Monitoring/Automation/Connections 분리)
- [x] Automation 페이지 (Webhooks + Scheduler + Swarm + Jobs + Containers)
- [x] Monitoring 페이지 (Events + Audit Log + Usage + Metrics + Approvals)
- [x] Connections 페이지 (Integrations + Messenger)
- [x] 사이드바 접기/펼치기

### Phase 2 (향후)
- Infrastructure UI (Connections > Infrastructure)
- Workers UI (Connections > Workers)
- 사이드바 드래그 순서 변경
- 키보드 단축키 (Cmd+K 검색)
- 알림 드로어

---

## 기존 코드 변경 영향

### 변경 필요 파일
1. `index.html` — 전체 레이아웃 구조 변경 (가장 큰 변경)
2. `css/glass-theme.css` — 사이드바 스타일 + 레이아웃 변수 추가
3. `js/chat.js` — `switchTab()` → `switchPage()` 참조 변경
4. `js/personal.js` — 탭 전환 참조 변경
5. `js/integrations.js` — Connections 페이지 내부로 이동
6. `js/plugins.js` — Explore 페이지 내부로 이동
7. `js/webhook.js` — Automation 페이지 내부로 이동
8. `js/quick-actions.js` — switchTab 참조 변경

### 새로 생성할 파일
1. `css/sidebar.css` — 사이드바 전용 스타일
2. `js/sidebar.js` — 사이드바 토글, 페이지 전환 로직
3. `js/automation.js` — Automation 페이지 통합 로직 (Scheduler/Swarm/Jobs/Containers 렌더링)
4. `js/monitoring-page.js` — Monitoring 페이지 확장 (Audit/Usage/Metrics/Approvals)
5. `js/connections.js` — Connections 페이지 통합 로직

### 변경 불필요
- 백엔드 API 라우트 — 변경 없음
- Python 코드 — 변경 없음
- 기존 JS 로직의 핵심 — API 호출/데이터 처리는 그대로 유지, 렌더링 타겟만 변경
