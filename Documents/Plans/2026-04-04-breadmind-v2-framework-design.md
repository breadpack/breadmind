# Breadmind v2: 도메인 무관 에이전트 프레임워크 설계

> 프로토콜이 계약을 정의하고, 모든 구현이 플러그인인, 도메인 무관 멀티 프로바이더 에이전트 프레임워크

## 1. 배경 및 동기

### 1.1 현재 Breadmind

Python 기반 AI 인프라 에이전트. FastAPI + Celery로 Kubernetes, Proxmox, OpenWrt를 자연어로 관리.

**강점:** 멀티 프로바이더 폴백, 3계층 메모리(Working/Episodic/Semantic + 지식그래프), Jinja2 모듈러 프롬프트, 의도 기반 도구 필터링, Iron Laws 안전장치.

**한계:** 인프라 도메인에 하드와이어링, 프롬프트 캐싱 없음, 단순 메시지 트리밍, 에이전트 루프 교체 불가, CLI 모드 없음.

### 1.2 Claude Code에서 가져올 것

| 기능 | 효과 |
|---|---|
| 프롬프트 캐싱 (정적/동적 2단 분리) | API 비용 절감 |
| 모델 주도 도구 검색 (deferred tools) | 도구 수 확장 시 토큰 절약 |
| 재귀적 서브에이전트 spawn | 무한 깊이 동적 위임 |
| `<system-reminder>` 컨텍스트 주입 | 대화 중간 자연스러운 컨텍스트 삽입 |
| LLM 기반 컨텍스트 압축 | 단순 트리밍 대비 정보 보존율 향상 |
| 스킬 시스템 | 사용자 확장 가능한 프롬프트 워크플로우 |
| Dream (메모리 정리) | 장기 메모리 자동 정리/압축 |

### 1.3 목표

- **도메인 무관:** 인프라, 코딩, 개인비서 등 어떤 도메인이든 에이전트를 만들 수 있는 프레임워크
- **2계층 사용자:** Python SDK(개발자) + YAML/자연어(비개발자)
- **2중 실행:** CLI + 서버(ASGI) 양쪽 동일 에이전트 실행
- **프로바이더별 최적화:** 멀티 프로바이더 호환 + 각 프로바이더 고유 기능 활용

---

## 2. 코어 아키텍처

### 2.1 원칙

**"프로토콜은 법, 구현은 플러그인"**

코어는 두 가지만 책임진다:
1. **프로토콜 정의** — 구성요소 간 계약 (Python Protocol/ABC)
2. **플러그인 라이프사이클** — 발견, 로드, 의존성 주입, 이벤트 라우팅

에이전트 루프, 프롬프트 빌더, 메모리, 프로바이더, 도구 — 전부 프로토콜을 구현하는 플러그인.

### 2.2 디렉토리 구조

```
breadmind/
├── core/                          # 마이크로 코어 (~1000줄 이하)
│   ├── protocols/                 # 프로토콜 정의 (계약만, 구현 없음)
│   │   ├── agent.py               # AgentProtocol
│   │   ├── provider.py            # ProviderProtocol
│   │   ├── prompt.py              # PromptProtocol
│   │   ├── tool.py                # ToolProtocol
│   │   ├── memory.py              # MemoryProtocol
│   │   └── runtime.py             # RuntimeProtocol
│   ├── plugin.py                  # 플러그인 로더 + 의존성 해석
│   ├── events.py                  # 타입드 이벤트 버스
│   └── container.py               # DI 컨테이너 (프로토콜 → 구현체 매핑)
│
├── plugins/
│   ├── builtin/                   # 기본 번들 (이것만으로 완전 동작)
│   │   ├── agent_loop/            # 기본 에이전트 루프
│   │   ├── providers/             # Claude, Gemini, Grok, Ollama 어댑터
│   │   ├── prompt_builder/        # Jinja2 기반 프롬프트 빌더
│   │   ├── memory/                # Working + Episodic + Semantic
│   │   ├── tools/                 # 기본 도구 (shell, file, web 등)
│   │   ├── safety/                # 안전장치 + autonomy level
│   │   └── runtimes/              # CLI, 서버, 임베디드
│   │
│   └── domains/                   # 도메인별 플러그인 번들
│       ├── infra/                 # 기존 Breadmind (k8s, proxmox, openwrt)
│       ├── coding/                # 코딩 에이전트
│       └── ...
│
├── sdk/                           # 개발자 SDK (Python API)
└── dsl/                           # 노코드 레이어 (YAML 파서)
```

### 2.3 플러그인 간 통신

플러그인끼리 직접 참조하지 않는다. 2가지 경로만 사용:

1. **프로토콜 DI** — 컨테이너가 구현체를 주입

```python
class MyAgentLoop(AgentProtocol):
    def __init__(self, provider: ProviderProtocol, memory: MemoryProtocol):
        ...  # DI 컨테이너가 구현체를 주입
```

2. **이벤트 버스** — 느슨한 결합

```python
events.emit("tool.executed", ToolResult(...))
events.emit("turn.completed", TurnResult(...))
events.emit("session.ended", SessionInfo(...))
```

---

## 3. 프로토콜 상세 설계

### 3.1 ProviderProtocol — LLM 호출 + 프로바이더별 최적화

```python
@runtime_checkable
class ProviderProtocol(Protocol):
    async def chat(
        self, messages: list[Message], tools: list[ToolSchema] | None = None,
        think_budget: int | None = None,
    ) -> LLMResponse: ...

    def get_cache_strategy(self) -> CacheStrategy | None:
        """Claude: 2단 캐시, Gemini: context caching, etc."""
        return None

    def supports_feature(self, feature: str) -> bool:
        """thinking_blocks, system_reminder, prompt_caching, tool_search"""
        return False

    def transform_system_prompt(self, blocks: list[PromptBlock]) -> Any:
        """PromptBlock 리스트를 프로바이더 네이티브 포맷으로 변환"""
        ...

    def transform_messages(self, messages: list[Message]) -> list[Any]:
        """Claude: <system-reminder> 주입, thinking block 처리 등"""
        ...

    @property
    def fallback(self) -> "ProviderProtocol | None":
        return None
```

### 3.2 PromptProtocol — 빌드/캐시/압축/주입

```python
@runtime_checkable
class PromptProtocol(Protocol):
    def build(self, context: PromptContext) -> list[PromptBlock]:
        """시스템 프롬프트 조립. 각 블록에 cacheable 힌트 포함"""
        ...

    def rebuild_dynamic(self, context: PromptContext) -> list[PromptBlock]:
        """동적 섹션만 재빌드 (매 턴 호출)"""
        ...

    async def compact(
        self, messages: list[Message], budget_tokens: int,
    ) -> CompactResult:
        """LLM 기반 컨텍스트 압축"""
        ...

    def inject_reminder(self, key: str, content: str) -> Message:
        """대화 중간 컨텍스트 주입"""
        ...
```

```python
@dataclass
class PromptBlock:
    section: str           # "identity", "iron_laws", "behaviors", ...
    content: str
    cacheable: bool        # True → 정적, False → 동적
    priority: int          # 토큰 트리밍 시 제거 순서 (0=불변, 높을수록 먼저 제거)
    provider_hints: dict   # {"claude": {"scope": "global"}, ...}
```

### 3.3 ToolProtocol — 등록/실행/하이브리드 검색

```python
@runtime_checkable
class ToolProtocol(Protocol):
    def register(self, tool: ToolDefinition) -> None: ...
    def unregister(self, name: str) -> None: ...

    def get_schemas(self, filter: ToolFilter | None = None) -> list[ToolSchema]:
        """활성 도구의 LLM용 스키마 반환"""
        ...

    async def execute(self, call: ToolCall, ctx: ExecutionContext) -> ToolResult: ...

    def get_deferred_tools(self) -> list[str]:
        """이름만 노출 (ToolSearch 패턴)"""
        return []

    def resolve_deferred(self, names: list[str]) -> list[ToolSchema]:
        """deferred 도구의 전체 스키마 반환"""
        ...
```

```python
@dataclass
class ToolFilter:
    intent: str | None = None        # Breadmind 의도 기반 필터
    keywords: list[str] | None = None
    always_include: list[str] | None = None
    max_tools: int | None = None
    use_deferred: bool = False        # Claude Code 스타일 deferred 사용 여부
```

**하이브리드 전략 자동 선택:**
- 프로바이더가 `supports_feature("tool_search")` + 도구 30개 초과 → deferred 모드
- 그 외 → 의도 기반 필터링 폴백

### 3.4 MemoryProtocol — 3계층 + 압축 + dream

```python
@runtime_checkable
class MemoryProtocol(Protocol):
    # Working (세션)
    async def working_get(self, session_id: str) -> list[Message]: ...
    async def working_put(self, session_id: str, messages: list[Message]) -> None: ...
    async def working_compress(self, session_id: str, budget: int) -> None: ...

    # Episodic (경험)
    async def episodic_search(self, query: str, limit: int = 5) -> list[Episode]: ...
    async def episodic_save(self, episode: Episode) -> None: ...

    # Semantic (지식그래프)
    async def semantic_query(self, entities: list[str]) -> list[KGTriple]: ...
    async def semantic_upsert(self, triples: list[KGTriple]) -> None: ...

    # Claude Code 흡수
    async def build_context_block(
        self, session_id: str, query: str, budget_tokens: int,
    ) -> PromptBlock:
        """메모리 검색 결과를 PromptBlock으로 패키징"""
        ...

    async def dream(self, session_id: str) -> None:
        """세션 종료 후 메모리 정리 (Orient → Gather → Consolidate → Prune)"""
        ...
```

### 3.5 AgentProtocol — 생명주기 + 재귀 spawn + swarm

```python
@runtime_checkable
class AgentProtocol(Protocol):
    @property
    def agent_id(self) -> str: ...

    async def handle_message(self, message: str, ctx: AgentContext) -> AgentResponse: ...

    async def spawn(
        self, prompt: str,
        tools: list[str] | None = None,
        isolation: str | None = None,
    ) -> "AgentProtocol":
        """재귀적 서브에이전트 생성"""
        ...

    async def send_message(self, target: str, message: str) -> str:
        """에이전트 간 메시지 패싱"""
        ...

    def set_role(self, role: str) -> None:
        """역할 전환 → 프롬프트 동적 재빌드"""
        ...
```

```python
@dataclass
class AgentContext:
    user: str
    channel: str
    session_id: str
    parent_agent: str | None = None
    depth: int = 0
    max_depth: int = 5
    isolation: str | None = None
```

**재귀 spawn + 선언적 swarm 공존:**

```python
# 동적: 에이전트가 필요 시 자식 spawn
sub = await agent.spawn("로그 분석", tools=["file_read"])

# 선언적: 태스크 그래프로 전문가 편성
await agent.execute_swarm(SwarmPlan(tasks=[
    SwarmTask("scan", role="security_analyst"),
    SwarmTask("fix", role="k8s_expert", depends_on=["scan"]),
]))
```

### 3.6 RuntimeProtocol — 실행 환경 추상화

```python
@runtime_checkable
class RuntimeProtocol(Protocol):
    async def start(self, container: Container) -> None: ...
    async def stop(self) -> None: ...
    async def receive(self) -> UserInput: ...
    async def send(self, output: AgentOutput) -> None: ...
    async def send_progress(self, progress: Progress) -> None: ...
```

구현체: `CLIRuntime`, `ServerRuntime` (ASGI), `EmbeddedRuntime` (함수 호출).

---

## 4. Claude Code 기능 이식 상세

### 4.1 프롬프트 캐싱

`PromptBlock.cacheable` + `provider_hints`로 프로바이더 무관 캐시 힌트를 정의하고, `ProviderProtocol.transform_system_prompt()`가 네이티브 포맷으로 변환.

```python
# Claude 어댑터: cacheable 블록에 cache_control 추가
param["cache_control"] = {"type": "ephemeral", "scope": scope}

# Gemini 어댑터: context caching API 활용
# Ollama 어댑터: 캐시 힌트 무시, 단순 concat
```

### 4.2 LLM 기반 컨텍스트 압축

WorkingMemory 임계값 도달 시 LLM 호출로 요약 생성:

1. 비텍스트 콘텐츠 → 마커 교체 (`[image]`, `[document]`)
2. 메시지를 API 라운드별 그룹화
3. LLM 호출 → 요약 생성
4. 경계 메시지 + 최근 메시지 보존

### 4.3 하이브리드 도구 검색

의도 기반 필터링(사전 축소) + deferred tools(모델 주도 탐색) 결합. 프로바이더 능력과 도구 수에 따라 자동 전략 선택.

### 4.4 재귀적 서브에이전트

`AgentProtocol.spawn()`으로 자식 에이전트를 동적 생성. `AgentContext.depth`로 무한 재귀 방지(기본 max_depth=5). 기존 Breadmind SwarmPlan 기반 선언적 방식도 공존.

### 4.5 `<system-reminder>` 일반화

`PromptProtocol.inject_reminder()`가 프로바이더별로 변환:
- Claude → `<system-reminder>` XML 태그 + user 메시지
- 범용 → system 메시지

사용 시점: 메모리 검색 결과, 스킬 로드, 도구 실행 후 부가 안내, 사용자 프로필.

### 4.6 Dream 시스템

`MemoryProtocol.dream()`이 세션 종료 이벤트(`session.ended`) 수신 시 비동기 실행:
1. Orient — 기존 장기 메모리 읽기
2. Gather — 세션에서 새 신호 수집
3. Consolidate — 병합 + 중복 제거
4. Prune — 오래된 기억 정리

### 4.7 스킬 시스템

`SkillTool`이 YAML 스킬 파일을 로드하여 `inject_reminder()`로 대화에 주입:

```yaml
# skills/k8s-troubleshoot.yaml
name: k8s-troubleshoot
description: Kubernetes 파드 장애 진단 워크플로우
trigger: "pod.*fail|crash|restart|OOM"
content: |
  ## 진단 순서
  1. 파드 상태 확인
  2. 로그 확인
  ...
```

---

## 5. SDK와 노코드 레이어

### 5.1 Python SDK

```python
# 최소 에이전트 (5줄)
from breadmind import Agent, tool

@tool(description="파일 읽기")
async def read_file(path: str) -> str:
    return open(path).read()

agent = Agent(name="FileReader", tools=[read_file])
response = await agent.run("config.yaml 읽어줘")
```

```python
# 풀 커스텀
agent = Agent(
    name="InfraOps",
    config=AgentConfig(provider="claude", model="claude-sonnet-4-6", fallback_provider="gemini", max_turns=15),
    prompt=PromptConfig(persona="professional", role="k8s_expert", language="ko"),
    memory=MemoryConfig(working=True, episodic=True, semantic=False, dream=True),
    tools=["shell_exec", "file_*", "k8s_*"],
    safety=SafetyConfig(autonomy="confirm-destructive"),
)

await agent.serve(runtime="cli")      # CLI
await agent.serve(runtime="server")   # 서버
```

```python
# 플러그인 교체
from my_plugin import TreeSearchLoop

agent = Agent(
    name="Researcher",
    plugins={"agent_loop": TreeSearchLoop(branching_factor=3)},
)
```

### 5.2 YAML DSL

SDK의 모든 옵션을 YAML로 1:1 대응. 런타임에 파싱하여 Agent 인스턴스 생성.

```yaml
name: IncidentResponder
config:
  provider: claude
  model: claude-sonnet-4-6
  fallback: gemini
  max_turns: 15

prompt:
  persona: professional
  role: k8s_expert
  language: ko

memory:
  working: true
  episodic: true
  dream: true

tools:
  include: [shell_exec, file_read, k8s_*]
  approve_required: [shell_exec, k8s_pods_delete]

safety:
  autonomy: confirm-destructive

sub_agents:
  - name: LogAnalyzer
    tools: [file_read, grep]

swarm:
  tasks:
    - id: diagnose
      agent: LogAnalyzer
    - id: respond
      role: k8s_expert
      depends_on: [diagnose]
```

```bash
breadmind run agents/incident-responder.yaml
breadmind run agents/incident-responder.yaml --runtime server --port 8000
```

### 5.3 자연어 에이전트 생성

```bash
breadmind create "쿠버네티스 장애 진단 에이전트"
```

LLM이 요구사항 분석 → 적절한 역할/도구/스킬 추천 → YAML 생성 → `agents/` 디렉토리 저장.

---

## 6. Autonomy Level (승인 제어)

```yaml
safety:
  autonomy: confirm-destructive   # 기본값
```

| 레벨 | 도구 실행 | 파일 변경 | 에이전트 생성 | 외부 API |
|---|---|---|---|---|
| `auto` | 즉시 | 즉시 | 즉시 | 즉시 |
| `confirm-destructive` | 파괴적만 확인 | 즉시 | 즉시 | 즉시 |
| `confirm-unsafe` | 파괴적 확인 | 확인 | 확인 | 확인 |
| `confirm-all` | 전부 확인 | 확인 | 확인 | 확인 |

`blocked_patterns`는 어떤 레벨에서든 무조건 차단, 승인 우회 불가.

---

## 7. 마이그레이션 전략

### 7.1 방식: 빅뱅 전환

하위 호환 래퍼 없음. 새 코어 완성 후 기존 코드 전면 교체.

```
main: 기존 Breadmind 유지
feature/framework-core: Phase 1~4 개발
Phase 5 완료 → main 머지, 기존 코드 삭제
```

### 7.2 마이그레이션 맵

| 현재 모듈 | 유형 | 새 위치 |
|---|---|---|
| `core/agent.py` | 재작성 | `core/protocols/` + `plugins/builtin/agent_loop/` |
| `core/bootstrap.py` | 재작성 | `core/container.py` + 엔트리포인트 |
| `core/tool_executor.py` | 재작성 | `core/protocols/tool.py` + `plugins/builtin/tools/executor.py` |
| `core/safety.py` | 이식 | `plugins/builtin/safety/` |
| `core/swarm.py` | 이식 | `plugins/builtin/agent_loop/spawner.py` |
| `core/smart_retriever.py` | 이식 | `plugins/builtin/memory/smart_retriever.py` |
| `prompts/builder.py` | 이식 | `plugins/builtin/prompt_builder/` |
| `prompts/*.j2` | 이동 | `plugins/builtin/prompt_builder/templates/` |
| `memory/working.py` | 이식+강화 | `plugins/builtin/memory/working.py` (LLM 압축 추가) |
| `memory/episodic.py` | 이식 | `plugins/builtin/memory/episodic.py` |
| `memory/semantic.py` | 이식 | `plugins/builtin/memory/semantic.py` |
| `memory/context_builder.py` | 이식 | `plugins/builtin/memory/context_builder.py` |
| `llm/base.py` | 재작성 | `core/protocols/provider.py` |
| `llm/claude.py` 등 | 이식+강화 | `plugins/builtin/providers/` |
| `tools/registry.py` | 재작성 | `core/protocols/tool.py` + `plugins/builtin/tools/registry.py` |
| `plugins/builtin/core_tools/` | 이동 | `plugins/builtin/tools/core/` |
| `plugins/builtin/network/` | 이동 | `plugins/domains/infra/` |
| `plugins/builtin/browser/` | 이동 | `plugins/builtin/tools/browser/` |
| `plugins/builtin/coding/` | 이동 | `plugins/domains/coding/` |
| `plugins/builtin/messenger/` | 이동 | `plugins/builtin/runtimes/messenger/` |
| `plugins/builtin/personal/` | 이동 | `plugins/domains/personal/` |
| `web/routes/` | 이식 | `plugins/builtin/runtimes/server/` |

### 7.3 Phase별 진행 및 검증

| Phase | 내용 | 완료 기준 |
|---|---|---|
| 1. 기반 | 6 프로토콜, DI 컨테이너, 이벤트 버스, 플러그인 로더 | `container.resolve(ProviderProtocol)` 동작 |
| 2. 엔진 | 프로바이더 어댑터, Jinja2 프롬프트 빌더, 에이전트 루프, 도구 레지스트리, 안전장치 | 단일 턴 대화: 시스템 프롬프트 → LLM 호출 → 텍스트 응답 |
| 3. 기능 | 기본 도구(shell, file, web), 3계층 메모리, LLM 압축, dream, 스킬 시스템 | 멀티턴 + 도구 호출 대화, 메모리 저장/검색 동작 |
| 4. 런타임 | CLI, 서버(ASGI), 임베디드 런타임, SDK, YAML DSL | `breadmind run agent.yaml --runtime cli/server` 양쪽 동작 |
| 5. 도메인 이식 | 기존 인프라 코드를 도메인 플러그인으로 이식 → main 머지 | 기존 인프라 명령이 도메인 플러그인으로 동일하게 동작 |

---

## 8. Claude Code 대비 우위

| 관점 | Claude Code | Breadmind v2 |
|---|---|---|
| 프로바이더 | Claude 단일 | 멀티 + 프로바이더별 최적화 어댑터 |
| 프롬프트 캐싱 | Claude 전용 2단 캐시 | 프로바이더 무관 블록 단위 캐시 힌트 |
| 도구 선택 | 모델 주도만 | 하이브리드 (의도 기반 + 모델 주도) |
| 멀티에이전트 | 재귀 spawn만 | 재귀 + 선언적 태스크 그래프 |
| 메모리 | 파일 기반 단일 계층 | DB 기반 3계층 + KG + LLM 압축 + dream |
| 프롬프트 설계 | 하드코딩 함수 체인 | Jinja2 템플릿 상속 + 역할/페르소나 교체 |
| 에이전트 정의 | 코드 내 고정 | SDK + YAML + 자연어 |
| 코어 교체 | 불가능 | 에이전트 루프까지 플러그인 교체 가능 |
| 실행 환경 | CLI + IDE 브릿지 | CLI + 서버 + 임베디드 |
| 승인 모델 | 퍼미션 모드 3단 | autonomy 4단 + 블랙리스트 |
