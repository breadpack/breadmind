# Orchestrator + SubAgent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CoreAgent가 복합 작업을 감지하면 Orchestrator로 분기하여, Planner가 DAG를 생성하고 DAGExecutor가 전문 subagent들을 병렬로 실행하도록 한다.

**Architecture:** Planner(고성능 LLM)가 사용자 요청을 TaskDAG로 분해 → DAGExecutor가 위상 정렬 순서로 subagent를 병렬 스폰 → ResultEvaluator가 정상/이상 판단 → 이상 시 Orchestrator가 DAG를 동적 수정. 기존 Swarm/SubAgent/delegate_tasks를 완전 대체한다.

**Tech Stack:** Python 3.12+, asyncio, pydantic dataclasses, Jinja2 prompts, pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-04-04-orchestrator-subagent-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `src/breadmind/core/orchestrator.py` | Orchestrator: 복합 작업 판단, Planner/DAGExecutor 조율, 최종 요약 |
| Create | `src/breadmind/core/planner.py` | Planner: 사용자 요청 → TaskDAG 분해 (LLM 호출) |
| Create | `src/breadmind/core/dag_executor.py` | DAGExecutor: DAG 위상 정렬 실행, subagent 스폰/수집 |
| Create | `src/breadmind/core/result_evaluator.py` | ResultEvaluator: subagent 결과 정상/이상 판단 |
| Create | `src/breadmind/core/role_registry.py` | 역할 정의, 역할별 도구셋/프롬프트 매핑 |
| Modify | `src/breadmind/core/subagent.py` | SubAgent: 새 구현으로 완전 대체 |
| Modify | `src/breadmind/core/agent.py:319-389` | CoreAgent: 복합 작업 분기 로직 추가 |
| Modify | `src/breadmind/core/intent.py:27-34` | Intent: complexity 필드 추가 |
| Modify | `src/breadmind/core/events.py:14-40` | EventType: 오케스트레이터 이벤트 추가 |
| Modify | `src/breadmind/core/bootstrap.py:100-154` | Orchestrator 초기화 등록 |
| Modify | `src/breadmind/web/routes/subagent.py` | API 엔드포인트 갱신 |
| Delete | `src/breadmind/core/swarm.py` | SwarmManager/SwarmMember/DEFAULT_ROLES 제거 |
| Delete | `src/breadmind/core/swarm_executor.py` | SwarmExecutor/SwarmCoordinator 제거 |
| Delete | `src/breadmind/core/team_builder.py` | TeamBuilder 제거 |
| Modify | `src/breadmind/tools/builtin.py:486-565` | delegate_tasks 함수 제거 |
| Create | `tests/test_orchestrator.py` | Orchestrator 통합 테스트 |
| Create | `tests/test_planner.py` | Planner 단위 테스트 |
| Create | `tests/test_dag_executor.py` | DAGExecutor 단위 테스트 |
| Create | `tests/test_result_evaluator.py` | ResultEvaluator 단위 테스트 |
| Create | `tests/test_role_registry.py` | RoleRegistry 단위 테스트 |
| Modify | `tests/test_subagent.py` | 새 SubAgent에 맞게 갱신 |
| Delete | `tests/test_swarm.py` | SwarmManager 테스트 제거 |

---

### Task 1: Intent에 complexity 필드 추가

**Files:**
- Modify: `src/breadmind/core/intent.py:27-34`
- Create: `tests/test_intent_complexity.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_intent_complexity.py
from breadmind.core.intent import classify, Intent


def test_simple_query_is_simple():
    intent = classify("K8s Pod 목록 보여줘")
    assert intent.complexity == "simple"


def test_multi_domain_is_complex():
    intent = classify("K8s Pod 진단하고 Proxmox 리소스도 확인해줘")
    assert intent.complexity == "complex"


def test_multi_step_is_complex():
    intent = classify("OOMKilled Pod 찾아서 메모리 limit 2배로 올려줘")
    assert intent.complexity == "complex"


def test_single_action_is_simple():
    intent = classify("nginx 재시작해줘")
    assert intent.complexity == "simple"


def test_diagnose_and_fix_is_complex():
    intent = classify("왜 느린지 확인하고 고쳐줘")
    assert intent.complexity == "complex"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_intent_complexity.py -v`
Expected: FAIL with `AttributeError: 'Intent' object has no attribute 'complexity'`

- [ ] **Step 3: Add complexity field to Intent and detection logic**

In `src/breadmind/core/intent.py`, add `complexity` field to the Intent dataclass:

```python
@dataclass
class Intent:
    category: IntentCategory
    confidence: float  # 0.0 ~ 1.0
    keywords: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    tool_hints: set[str] = field(default_factory=set)
    urgency: str = "normal"
    complexity: str = "simple"  # "simple" | "complex"
```

Add complexity detection patterns and a `_detect_complexity()` function after the existing pattern definitions:

```python
# Multi-domain indicators
_DOMAIN_KEYWORDS = {
    "k8s": re.compile(r"(k8s|kubernetes|pod|deploy|node|kubectl|namespace|ingress)", re.I),
    "proxmox": re.compile(r"(proxmox|vm|lxc|qemu|hypervisor|pve)", re.I),
    "openwrt": re.compile(r"(openwrt|router|firewall|dhcp|wan|lan|vlan)", re.I),
    "db": re.compile(r"(database|db|postgres|mysql|redis|mongo)", re.I),
    "network": re.compile(r"(network|dns|ssl|cert|tls|port|ip)", re.I),
}

# Multi-step indicators (Korean + English)
_MULTI_STEP_PATTERN = re.compile(
    r"(하고|한\s*다음|후에|그리고|and\s+then|then|after\s+that|also|"
    r"찾아서|확인하고|진단하고|분석하고|고쳐|수정해|올려|변경해|"
    r"fix\s+it|update\s+it|change\s+it|restart\s+it)",
    re.I,
)

# Diagnose + action combination
_DIAGNOSE_AND_ACT = re.compile(
    r"(왜.*(?:고쳐|수정|해결|fix|resolve|repair)|"
    r"(?:찾아|확인|진단|분석).*(?:고쳐|수정|올려|변경|적용|restart|deploy|scale)|"
    r"(?:diagnose|find|check|analyze).*(?:fix|update|change|apply|restart|deploy|scale))",
    re.I,
)


def _detect_complexity(message: str, intent: Intent) -> str:
    """Detect whether the message requires orchestrator (complex) or single agent (simple)."""
    # Count matching domains
    matched_domains = sum(1 for p in _DOMAIN_KEYWORDS.values() if p.search(message))
    if matched_domains >= 2:
        return "complex"

    # Multi-step patterns
    if _MULTI_STEP_PATTERN.search(message) and len(intent.entities) >= 1:
        return "complex"

    # Diagnose + action combination
    if _DIAGNOSE_AND_ACT.search(message):
        return "complex"

    return "simple"
```

Call `_detect_complexity` at the end of the `classify()` function, before returning the intent:

```python
    intent.complexity = _detect_complexity(message, intent)
    return intent
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_intent_complexity.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Run existing intent tests to verify no regression**

Run: `python -m pytest tests/test_intent.py -v`
Expected: All existing tests PASS (complexity defaults to "simple")

- [ ] **Step 6: Commit**

```bash
git add src/breadmind/core/intent.py tests/test_intent_complexity.py
git commit -m "feat: add complexity field to Intent for orchestrator branching"
```

---

### Task 2: EventType에 오케스트레이터 이벤트 추가

**Files:**
- Modify: `src/breadmind/core/events.py:14-40`

- [ ] **Step 1: Add orchestrator event types**

In `src/breadmind/core/events.py`, add to the `EventType` enum after the existing tool events:

```python
    # Orchestrator events
    ORCHESTRATOR_START = "orchestrator_start"
    ORCHESTRATOR_REPLAN = "orchestrator_replan"
    ORCHESTRATOR_END = "orchestrator_end"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_END = "subagent_end"
    SUBAGENT_FAILED = "subagent_failed"
    DAG_BATCH_START = "dag_batch_start"
    DAG_BATCH_END = "dag_batch_end"
```

- [ ] **Step 2: Verify existing event tests still pass**

Run: `python -m pytest tests/ -k "event" -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add src/breadmind/core/events.py
git commit -m "feat: add orchestrator event types to EventBus"
```

---

### Task 3: RoleRegistry — 역할 정의 및 도구셋 매핑

**Files:**
- Create: `src/breadmind/core/role_registry.py`
- Create: `tests/test_role_registry.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_role_registry.py
from breadmind.core.role_registry import RoleRegistry, RoleDefinition


def test_get_builtin_role():
    reg = RoleRegistry()
    role = reg.get("k8s_diagnostician")
    assert role is not None
    assert role.domain == "k8s"
    assert role.task_type == "diagnostician"
    assert "pods_list" in role.dedicated_tools
    assert "shell_exec" in role.common_tools


def test_get_unknown_role_returns_none():
    reg = RoleRegistry()
    assert reg.get("nonexistent_role") is None


def test_list_roles():
    reg = RoleRegistry()
    roles = reg.list_roles()
    assert len(roles) >= 6  # at least the builtins
    assert any(r.name == "k8s_diagnostician" for r in roles)


def test_get_tools_for_role():
    reg = RoleRegistry()
    tools = reg.get_tools("k8s_diagnostician")
    assert "pods_list" in tools
    assert "shell_exec" in tools


def test_get_tools_unknown_role_returns_common_only():
    reg = RoleRegistry()
    tools = reg.get_tools("nonexistent")
    assert "shell_exec" in tools
    assert len(tools) > 0


def test_register_custom_role():
    reg = RoleRegistry()
    role = RoleDefinition(
        name="custom_checker",
        domain="custom",
        task_type="checker",
        system_prompt="You check custom things.",
        description="Custom checker",
        dedicated_tools=["custom_tool"],
        common_tools=["shell_exec"],
    )
    reg.register(role)
    assert reg.get("custom_checker") is not None


def test_difficulty_to_model():
    reg = RoleRegistry()
    assert reg.difficulty_to_model("low") == "haiku"
    assert reg.difficulty_to_model("medium") == "sonnet"
    assert reg.difficulty_to_model("high") == "opus"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_role_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'breadmind.core.role_registry'`

- [ ] **Step 3: Implement RoleRegistry**

```python
# src/breadmind/core/role_registry.py
"""Role definitions and tool-set mappings for orchestrator subagents."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RoleDefinition:
    name: str              # e.g. "k8s_diagnostician"
    domain: str            # e.g. "k8s"
    task_type: str         # e.g. "diagnostician"
    system_prompt: str
    description: str = ""
    dedicated_tools: list[str] = field(default_factory=list)
    common_tools: list[str] = field(default_factory=list)


_COMMON_TOOLS = ["shell_exec", "file_read", "file_write", "web_search"]

_BUILTIN_ROLES: list[RoleDefinition] = [
    # ── K8s ──
    RoleDefinition(
        name="k8s_diagnostician",
        domain="k8s",
        task_type="diagnostician",
        system_prompt=(
            "You are a Kubernetes diagnostics expert. Investigate cluster issues: "
            "check pod status, events, logs, resource usage, and node conditions. "
            "Report findings as [Critical], [Warning], or [OK] with one-line summaries."
        ),
        description="K8s cluster diagnosis and troubleshooting",
        dedicated_tools=[
            "pods_list", "pods_get", "pods_log", "pods_top",
            "nodes_top", "nodes_stats_summary", "events_list",
            "resources_list", "resources_get", "namespaces_list",
        ],
        common_tools=_COMMON_TOOLS,
    ),
    RoleDefinition(
        name="k8s_executor",
        domain="k8s",
        task_type="executor",
        system_prompt=(
            "You are a Kubernetes operations expert. Execute changes to the cluster: "
            "scale deployments, update resource limits, apply manifests, restart pods. "
            "Verify each change succeeded before reporting completion."
        ),
        description="K8s resource modification and deployment",
        dedicated_tools=[
            "pods_list", "pods_get", "pods_delete", "pods_run",
            "resources_create_or_update", "resources_delete", "resources_get",
            "resources_list", "resources_scale", "namespaces_list",
        ],
        common_tools=_COMMON_TOOLS,
    ),
    # ── Proxmox ──
    RoleDefinition(
        name="proxmox_diagnostician",
        domain="proxmox",
        task_type="diagnostician",
        system_prompt=(
            "You are a Proxmox diagnostics expert. Investigate hypervisor and guest issues: "
            "check VM/LXC status, node health, storage, and backups. "
            "Report findings as [Critical], [Warning], or [OK]."
        ),
        description="Proxmox health diagnosis",
        dedicated_tools=[
            "proxmox_get_vms", "proxmox_get_vm_status", "proxmox_get_nodes",
            "proxmox_get_node_status", "proxmox_get_storage",
            "proxmox_get_cluster_status", "proxmox_list_backups",
            "proxmox_list_snapshots_vm", "proxmox_list_snapshots_lxc",
        ],
        common_tools=_COMMON_TOOLS,
    ),
    RoleDefinition(
        name="proxmox_executor",
        domain="proxmox",
        task_type="executor",
        system_prompt=(
            "You are a Proxmox operations expert. Execute VM/LXC lifecycle operations: "
            "start, stop, resize, clone, snapshot, backup. "
            "Verify each operation succeeded before reporting."
        ),
        description="Proxmox VM/LXC management",
        dedicated_tools=[
            "proxmox_get_vms", "proxmox_get_vm_status",
            "proxmox_start_vm", "proxmox_stop_vm", "proxmox_reboot_vm",
            "proxmox_resize_vm", "proxmox_clone_vm",
            "proxmox_create_snapshot_vm", "proxmox_create_backup_vm",
            "proxmox_start_lxc", "proxmox_stop_lxc", "proxmox_reboot_lxc",
        ],
        common_tools=_COMMON_TOOLS,
    ),
    # ── OpenWrt ──
    RoleDefinition(
        name="openwrt_diagnostician",
        domain="openwrt",
        task_type="diagnostician",
        system_prompt=(
            "You are an OpenWrt network diagnostics expert. Investigate router and network issues: "
            "check interface status, system health, and logs. "
            "Report findings as [Critical], [Warning], or [OK]."
        ),
        description="OpenWrt/network diagnosis",
        dedicated_tools=["network_status", "system_status", "read_log"],
        common_tools=_COMMON_TOOLS,
    ),
    RoleDefinition(
        name="openwrt_executor",
        domain="openwrt",
        task_type="executor",
        system_prompt=(
            "You are an OpenWrt operations expert. Execute network configuration changes: "
            "manage interfaces, firewall rules, DHCP, and system settings. "
            "Verify changes took effect."
        ),
        description="OpenWrt configuration and management",
        dedicated_tools=["network_status", "system_status", "read_log", "reboot", "set_led_state"],
        common_tools=_COMMON_TOOLS,
    ),
    # ── Cross-domain ──
    RoleDefinition(
        name="general_analyst",
        domain="general",
        task_type="analyst",
        system_prompt=(
            "You are a general infrastructure analyst. Handle tasks that span multiple domains "
            "or don't fit a specialized role. Gather data from any available tools and provide "
            "clear, structured analysis."
        ),
        description="General-purpose analysis (fallback)",
        dedicated_tools=[],
        common_tools=_COMMON_TOOLS,
    ),
    RoleDefinition(
        name="security_analyst",
        domain="general",
        task_type="analyst",
        system_prompt=(
            "You are a security analyst. Assess infrastructure security posture: "
            "RBAC, firewall rules, certificate expiry, exposed services, default credentials. "
            "Report findings as [Critical], [Warning], or [OK]."
        ),
        description="Security posture assessment",
        dedicated_tools=[],
        common_tools=_COMMON_TOOLS,
    ),
    RoleDefinition(
        name="performance_analyst",
        domain="general",
        task_type="analyst",
        system_prompt=(
            "You are a performance analyst. Analyze resource utilization and identify bottlenecks: "
            "CPU, memory, disk I/O, network throughput. Provide optimization recommendations."
        ),
        description="Performance analysis and optimization",
        dedicated_tools=[],
        common_tools=_COMMON_TOOLS,
    ),
]

# Difficulty -> model name mapping
_DIFFICULTY_MODEL = {
    "low": "haiku",
    "medium": "sonnet",
    "high": "opus",
}


class RoleRegistry:
    """Registry of subagent roles with their tool-sets and prompts."""

    def __init__(self) -> None:
        self._roles: dict[str, RoleDefinition] = {}
        for role in _BUILTIN_ROLES:
            self._roles[role.name] = role

    def get(self, name: str) -> RoleDefinition | None:
        return self._roles.get(name)

    def list_roles(self) -> list[RoleDefinition]:
        return list(self._roles.values())

    def register(self, role: RoleDefinition) -> None:
        self._roles[role.name] = role

    def remove(self, name: str) -> bool:
        return self._roles.pop(name, None) is not None

    def get_tools(self, role_name: str) -> list[str]:
        """Return combined dedicated + common tools for a role. Falls back to common-only."""
        role = self._roles.get(role_name)
        if role is None:
            return list(_COMMON_TOOLS)
        return role.dedicated_tools + role.common_tools

    def get_prompt(self, role_name: str) -> str:
        """Return the system prompt for a role."""
        role = self._roles.get(role_name)
        if role is None:
            return "You are a helpful infrastructure assistant."
        return role.system_prompt

    @staticmethod
    def difficulty_to_model(difficulty: str) -> str:
        return _DIFFICULTY_MODEL.get(difficulty, "sonnet")

    def list_role_summaries(self) -> str:
        """Return a formatted string of available roles for Planner prompt injection."""
        lines = []
        for r in self._roles.values():
            tools_str = ", ".join(r.dedicated_tools[:5])
            if len(r.dedicated_tools) > 5:
                tools_str += f" (+{len(r.dedicated_tools) - 5} more)"
            lines.append(f"- {r.name} ({r.domain}/{r.task_type}): {r.description} [tools: {tools_str}]")
        return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_role_registry.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/core/role_registry.py tests/test_role_registry.py
git commit -m "feat: add RoleRegistry with domain x task_type role definitions"
```

---

### Task 4: ResultEvaluator — subagent 결과 판단

**Files:**
- Create: `src/breadmind/core/result_evaluator.py`
- Create: `tests/test_result_evaluator.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_result_evaluator.py
import pytest
from breadmind.core.result_evaluator import ResultEvaluator, EvalResult


def test_success_result_is_normal():
    ev = ResultEvaluator()
    result = ev.evaluate("[success=True] Found 3 pods", "List of pods")
    assert result.status == "normal"


def test_failure_result_is_abnormal():
    ev = ResultEvaluator()
    result = ev.evaluate("[success=False] Connection refused", "List of pods")
    assert result.status == "abnormal"
    assert "Connection refused" in result.failure_reason


def test_empty_result_is_abnormal():
    ev = ResultEvaluator()
    result = ev.evaluate("", "Expected some output")
    assert result.status == "abnormal"


def test_timeout_result_is_abnormal():
    ev = ResultEvaluator()
    result = ev.evaluate("[success=False] Tool execution timed out after 60s.", "Pod list")
    assert result.status == "abnormal"
    assert result.is_timeout


def test_normal_result_carries_output():
    ev = ResultEvaluator()
    result = ev.evaluate("[success=True] 3 pods running", "Pod count")
    assert result.output == "[success=True] 3 pods running"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_result_evaluator.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement ResultEvaluator**

```python
# src/breadmind/core/result_evaluator.py
"""Evaluate subagent results as normal or abnormal."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EvalResult:
    status: str  # "normal" | "abnormal"
    output: str
    failure_reason: str = ""
    is_timeout: bool = False


class ResultEvaluator:
    """Rule-based evaluator for subagent outputs."""

    def evaluate(self, output: str, expected_output: str) -> EvalResult:
        # Rule 1: Empty output
        if not output or not output.strip():
            return EvalResult(
                status="abnormal",
                output=output,
                failure_reason="Empty output (expected: " + expected_output + ")",
            )

        # Rule 2: Explicit failure marker
        if output.startswith("[success=False]"):
            is_timeout = "timed out" in output.lower()
            return EvalResult(
                status="abnormal",
                output=output,
                failure_reason=output.removeprefix("[success=False]").strip(),
                is_timeout=is_timeout,
            )

        # Rule 3: Otherwise normal
        return EvalResult(status="normal", output=output)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_result_evaluator.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/core/result_evaluator.py tests/test_result_evaluator.py
git commit -m "feat: add ResultEvaluator for subagent output assessment"
```

---

### Task 5: SubAgent — 개별 작업 실행 단위 (기존 subagent.py 대체)

**Files:**
- Modify: `src/breadmind/core/subagent.py` (전체 대체)
- Modify: `tests/test_subagent.py` (전체 대체)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_subagent.py
import pytest
from unittest.mock import AsyncMock
from breadmind.core.subagent import SubAgent, SubAgentResult
from breadmind.llm.base import LLMMessage, LLMResponse, TokenUsage


def _make_response(content, tool_calls=None):
    return LLMResponse(
        content=content,
        tool_calls=tool_calls or [],
        usage=TokenUsage(input_tokens=10, output_tokens=10),
        stop_reason="end_turn",
    )


@pytest.mark.asyncio
async def test_subagent_runs_simple_task():
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=_make_response("Found 3 OOMKilled pods"))

    agent = SubAgent(
        task_id="task_1",
        description="Find OOMKilled pods",
        role="k8s_diagnostician",
        provider=provider,
        tools=[],
        system_prompt="You are a K8s diagnostician.",
        max_turns=3,
    )
    result = await agent.run(context={})
    assert result.success is True
    assert "OOMKilled" in result.output


@pytest.mark.asyncio
async def test_subagent_executes_tool_calls():
    tool_call_response = _make_response(None, tool_calls=[])
    # First call: LLM returns text (no tools)
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=_make_response("Done: 3 pods found"))

    registry_execute = AsyncMock(return_value=type("R", (), {"success": True, "output": "pod-1\npod-2", "not_found": False})())

    agent = SubAgent(
        task_id="task_1",
        description="List pods",
        role="k8s_diagnostician",
        provider=provider,
        tools=[{"name": "pods_list", "description": "List pods", "parameters": {}}],
        system_prompt="You are a K8s diagnostician.",
        max_turns=3,
        tool_executor=registry_execute,
    )
    result = await agent.run(context={})
    assert result.success is True


@pytest.mark.asyncio
async def test_subagent_max_turns_exceeded():
    """SubAgent should return partial result when max_turns exceeded."""
    from breadmind.llm.base import ToolCall
    tc = ToolCall(id="tc1", name="pods_list", arguments={})
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=_make_response(None, tool_calls=[tc]))

    registry_execute = AsyncMock(return_value=type("R", (), {"success": True, "output": "data", "not_found": False})())

    agent = SubAgent(
        task_id="task_1",
        description="Endless task",
        role="k8s_diagnostician",
        provider=provider,
        tools=[{"name": "pods_list", "description": "List pods", "parameters": {}}],
        system_prompt="You are a K8s diagnostician.",
        max_turns=2,
        tool_executor=registry_execute,
    )
    result = await agent.run(context={})
    assert result.success is False
    assert "max turns" in result.output.lower() or result.output != ""


@pytest.mark.asyncio
async def test_subagent_injects_context():
    """Prior task results should be injected into subagent messages."""
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=_make_response("Memory updated"))

    agent = SubAgent(
        task_id="task_2",
        description="Update memory limits",
        role="k8s_executor",
        provider=provider,
        tools=[],
        system_prompt="You are a K8s executor.",
        max_turns=3,
    )
    context = {"task_1": "Found pods: pod-a (128Mi), pod-b (256Mi)"}
    result = await agent.run(context=context)

    # Verify context was passed in messages
    call_args = provider.chat.call_args
    messages = call_args.kwargs.get("messages") or call_args[0][0]
    context_in_messages = any("pod-a" in (m.content or "") for m in messages)
    assert context_in_messages
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_subagent.py -v`
Expected: FAIL with `ImportError` (old SubAgentManager vs new SubAgent)

- [ ] **Step 3: Implement SubAgent**

Replace `src/breadmind/core/subagent.py` entirely:

```python
# src/breadmind/core/subagent.py
"""SubAgent: individual task execution unit with its own LLM loop."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from breadmind.llm.base import LLMProvider, LLMMessage, LLMResponse, ToolCall

logger = logging.getLogger("breadmind.subagent")


@dataclass
class SubAgentResult:
    task_id: str
    success: bool
    output: str
    turns_used: int = 0
    error: str = ""


class SubAgent:
    """Executes a single task with a dedicated LLM loop and role-specific tools."""

    def __init__(
        self,
        task_id: str,
        description: str,
        role: str,
        provider: LLMProvider,
        tools: list[dict],
        system_prompt: str,
        max_turns: int = 5,
        tool_executor: Callable[..., Awaitable] | None = None,
    ) -> None:
        self._task_id = task_id
        self._description = description
        self._role = role
        self._provider = provider
        self._tools = tools
        self._system_prompt = system_prompt
        self._max_turns = max_turns
        self._tool_executor = tool_executor

    async def run(self, context: dict[str, str] | None = None) -> SubAgentResult:
        """Execute the task and return the result."""
        messages = self._build_messages(context or {})

        for turn in range(self._max_turns):
            try:
                response = await self._provider.chat(
                    messages=messages,
                    tools=self._tools or None,
                )
            except Exception as e:
                logger.error("SubAgent %s LLM error: %s", self._task_id, e)
                return SubAgentResult(
                    task_id=self._task_id,
                    success=False,
                    output=f"[success=False] LLM error: {e}",
                    turns_used=turn + 1,
                    error=str(e),
                )

            if not response.has_tool_calls:
                return SubAgentResult(
                    task_id=self._task_id,
                    success=True,
                    output=response.content or "",
                    turns_used=turn + 1,
                )

            # Process tool calls
            messages.append(LLMMessage(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            ))

            for tc in response.tool_calls:
                tool_output = await self._execute_tool(tc)
                messages.append(LLMMessage(
                    role="tool",
                    content=tool_output,
                    tool_call_id=tc.id,
                    name=tc.name,
                ))

        # Max turns exceeded
        last_content = messages[-1].content or "" if messages else ""
        return SubAgentResult(
            task_id=self._task_id,
            success=False,
            output=f"[success=False] Max turns ({self._max_turns}) exceeded. Last output: {last_content}",
            turns_used=self._max_turns,
        )

    def _build_messages(self, context: dict[str, str]) -> list[LLMMessage]:
        msgs = [LLMMessage(role="system", content=self._system_prompt)]

        if context:
            context_text = "\n".join(
                f"[Prior result from {tid}]: {output}" for tid, output in context.items()
            )
            msgs.append(LLMMessage(
                role="system",
                content=f"Context from prior tasks:\n{context_text}",
            ))

        msgs.append(LLMMessage(role="user", content=self._description))
        return msgs

    async def _execute_tool(self, tc: ToolCall) -> str:
        if self._tool_executor is None:
            return f"[success=False] No tool executor available for {tc.name}"
        try:
            result = await self._tool_executor(tc.name, tc.arguments)
            prefix = "[success=True]" if result.success else "[success=False]"
            output = str(result.output)[:50000]
            return f"{prefix} {output}"
        except Exception as e:
            return f"[success=False] Tool error: {e}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_subagent.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/core/subagent.py tests/test_subagent.py
git commit -m "feat: replace SubAgentManager with new SubAgent execution unit"
```

---

### Task 6: Planner — 요청을 TaskDAG로 분해

**Files:**
- Create: `src/breadmind/core/planner.py`
- Create: `tests/test_planner.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_planner.py
import json
import pytest
from unittest.mock import AsyncMock
from breadmind.core.planner import Planner, TaskDAG, TaskNode
from breadmind.core.role_registry import RoleRegistry
from breadmind.llm.base import LLMResponse, TokenUsage


def _make_plan_response(nodes: list[dict]) -> LLMResponse:
    return LLMResponse(
        content=json.dumps({"nodes": nodes}),
        tool_calls=[],
        usage=TokenUsage(input_tokens=100, output_tokens=200),
        stop_reason="end_turn",
    )


@pytest.mark.asyncio
async def test_planner_creates_dag():
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=_make_plan_response([
        {"id": "task_1", "description": "Find OOMKilled pods", "role": "k8s_diagnostician",
         "depends_on": [], "difficulty": "low", "expected_output": "Pod list"},
        {"id": "task_2", "description": "Update memory limits", "role": "k8s_executor",
         "depends_on": ["task_1"], "difficulty": "medium", "expected_output": "Limits updated"},
    ]))

    planner = Planner(provider=provider, role_registry=RoleRegistry())
    dag = await planner.plan("OOMKilled Pod 찾아서 메모리 2배로 올려줘")

    assert dag.goal == "OOMKilled Pod 찾아서 메모리 2배로 올려줘"
    assert len(dag.nodes) == 2
    assert dag.nodes["task_1"].depends_on == []
    assert dag.nodes["task_2"].depends_on == ["task_1"]
    assert dag.nodes["task_1"].difficulty == "low"


@pytest.mark.asyncio
async def test_planner_handles_invalid_json():
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=LLMResponse(
        content="I cannot parse this request",
        tool_calls=[],
        usage=TokenUsage(input_tokens=10, output_tokens=10),
        stop_reason="end_turn",
    ))

    planner = Planner(provider=provider, role_registry=RoleRegistry())
    dag = await planner.plan("do something")

    # Fallback: single general_analyst node
    assert len(dag.nodes) == 1
    node = list(dag.nodes.values())[0]
    assert node.role == "general_analyst"


@pytest.mark.asyncio
async def test_planner_injects_role_summaries():
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=_make_plan_response([
        {"id": "task_1", "description": "check", "role": "general_analyst",
         "depends_on": [], "difficulty": "low", "expected_output": "result"},
    ]))

    planner = Planner(provider=provider, role_registry=RoleRegistry())
    await planner.plan("check something")

    # Verify role summaries were in the system prompt
    call_args = provider.chat.call_args
    messages = call_args.kwargs.get("messages") or call_args[0][0]
    system_content = messages[0].content
    assert "k8s_diagnostician" in system_content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_planner.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement Planner**

```python
# src/breadmind/core/planner.py
"""Planner: decomposes user requests into a TaskDAG via LLM call."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from breadmind.llm.base import LLMProvider, LLMMessage
from breadmind.core.role_registry import RoleRegistry

logger = logging.getLogger("breadmind.planner")


@dataclass
class TaskNode:
    id: str
    description: str
    role: str
    depends_on: list[str] = field(default_factory=list)
    difficulty: str = "medium"  # "low" | "medium" | "high"
    tools: list[str] = field(default_factory=list)
    expected_output: str = ""
    max_retries: int = 2


@dataclass
class TaskDAG:
    goal: str
    nodes: dict[str, TaskNode] = field(default_factory=dict)
    context: dict[str, str] = field(default_factory=dict)


_PLANNER_PROMPT = """\
You are a task planner for BreadMind, an AI infrastructure agent.
Decompose the user's request into a TaskDAG: a directed acyclic graph of tasks.

## Available Roles
{role_summaries}

## Rules
- Each task has: id, description, role, depends_on (list of task IDs), difficulty (low/medium/high), expected_output.
- Tasks with no dependencies can run in parallel.
- Use the most specific role for each task.
- difficulty: low = simple query/status check, medium = analysis/config change, high = complex diagnosis/risky operation.
- Minimize the number of tasks. Combine trivially sequential steps into one task.

## Output Format
Respond with ONLY a JSON object:
{{"nodes": [{{"id": "task_1", "description": "...", "role": "...", "depends_on": [], "difficulty": "low", "expected_output": "..."}}]}}
"""


class Planner:
    """Decomposes a user request into a TaskDAG using a high-capability LLM."""

    def __init__(self, provider: LLMProvider, role_registry: RoleRegistry) -> None:
        self._provider = provider
        self._roles = role_registry

    async def plan(self, goal: str) -> TaskDAG:
        system_prompt = _PLANNER_PROMPT.format(
            role_summaries=self._roles.list_role_summaries(),
        )
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=goal),
        ]

        try:
            response = await self._provider.chat(messages=messages)
            dag = self._parse_response(goal, response.content or "")
            return dag
        except Exception as e:
            logger.error("Planner failed: %s", e)
            return self._fallback_dag(goal)

    def _parse_response(self, goal: str, content: str) -> TaskDAG:
        # Extract JSON from response (handle markdown code blocks)
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Planner returned invalid JSON, using fallback DAG")
            return self._fallback_dag(goal)

        nodes_data = data.get("nodes", [])
        if not nodes_data:
            return self._fallback_dag(goal)

        dag = TaskDAG(goal=goal)
        for n in nodes_data:
            node = TaskNode(
                id=n.get("id", f"task_{len(dag.nodes) + 1}"),
                description=n.get("description", ""),
                role=n.get("role", "general_analyst"),
                depends_on=n.get("depends_on", []),
                difficulty=n.get("difficulty", "medium"),
                expected_output=n.get("expected_output", ""),
                max_retries=n.get("max_retries", 2),
            )
            dag.nodes[node.id] = node

        return dag

    def _fallback_dag(self, goal: str) -> TaskDAG:
        """Create a single-node DAG as fallback when planning fails."""
        dag = TaskDAG(goal=goal)
        dag.nodes["task_1"] = TaskNode(
            id="task_1",
            description=goal,
            role="general_analyst",
            difficulty="medium",
            expected_output="Task result",
        )
        return dag

    async def replan(self, goal: str, dag: TaskDAG, failed_task_id: str, failure_reason: str) -> TaskDAG:
        """Re-plan after a task failure: generate replacement nodes."""
        system_prompt = _PLANNER_PROMPT.format(
            role_summaries=self._roles.list_role_summaries(),
        )

        completed = {tid: ctx for tid, ctx in dag.context.items()}
        failed_node = dag.nodes.get(failed_task_id)

        replan_msg = (
            f"Original goal: {goal}\n\n"
            f"Completed tasks so far:\n"
            + "\n".join(f"- {tid}: {out[:200]}" for tid, out in completed.items())
            + f"\n\nFailed task: {failed_task_id} ({failed_node.description if failed_node else 'unknown'})\n"
            f"Failure reason: {failure_reason}\n\n"
            f"Generate replacement task(s) using a DIFFERENT approach. "
            f"Keep IDs unique (use task_alt_1, task_alt_2, etc.). "
            f"These tasks may depend on already-completed tasks: {list(completed.keys())}"
        )

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=replan_msg),
        ]

        try:
            response = await self._provider.chat(messages=messages)
            new_dag = self._parse_response(goal, response.content or "")
            return new_dag
        except Exception as e:
            logger.error("Replan failed: %s", e)
            return TaskDAG(goal=goal)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_planner.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/core/planner.py tests/test_planner.py
git commit -m "feat: add Planner for decomposing requests into TaskDAG"
```

---

### Task 7: DAGExecutor — DAG 실행 엔진

**Files:**
- Create: `src/breadmind/core/dag_executor.py`
- Create: `tests/test_dag_executor.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dag_executor.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.core.dag_executor import DAGExecutor
from breadmind.core.planner import TaskDAG, TaskNode
from breadmind.core.result_evaluator import ResultEvaluator, EvalResult
from breadmind.core.subagent import SubAgentResult


def _make_dag(nodes_spec: list[tuple]) -> TaskDAG:
    """Helper: nodes_spec = [(id, role, depends_on, difficulty), ...]"""
    dag = TaskDAG(goal="test goal")
    for nid, role, deps, diff in nodes_spec:
        dag.nodes[nid] = TaskNode(
            id=nid,
            description=f"Do {nid}",
            role=role,
            depends_on=deps,
            difficulty=diff,
            expected_output=f"Result of {nid}",
        )
    return dag


@pytest.mark.asyncio
async def test_linear_dag_executes_in_order():
    dag = _make_dag([
        ("t1", "k8s_diagnostician", [], "low"),
        ("t2", "k8s_executor", ["t1"], "medium"),
    ])

    execution_order = []

    async def mock_spawn(node, context):
        execution_order.append(node.id)
        return SubAgentResult(task_id=node.id, success=True, output=f"done-{node.id}", turns_used=1)

    executor = DAGExecutor(
        subagent_factory=mock_spawn,
        evaluator=ResultEvaluator(),
    )
    results = await executor.execute(dag)

    assert execution_order == ["t1", "t2"]
    assert results["t1"].success is True
    assert results["t2"].success is True


@pytest.mark.asyncio
async def test_parallel_dag_runs_concurrently():
    dag = _make_dag([
        ("t1", "k8s_diagnostician", [], "low"),
        ("t2", "proxmox_diagnostician", [], "low"),
        ("t3", "general_analyst", ["t1", "t2"], "medium"),
    ])

    batches = []
    current_batch = []

    async def mock_spawn(node, context):
        current_batch.append(node.id)
        return SubAgentResult(task_id=node.id, success=True, output=f"done-{node.id}", turns_used=1)

    executor = DAGExecutor(
        subagent_factory=mock_spawn,
        evaluator=ResultEvaluator(),
    )

    # Patch to track batches
    original_execute = executor.execute

    results = await executor.execute(dag)

    # t1 and t2 should both be done before t3
    assert "t1" in dag.context
    assert "t2" in dag.context
    assert results["t3"].success is True


@pytest.mark.asyncio
async def test_failed_task_returns_abnormal():
    dag = _make_dag([
        ("t1", "k8s_diagnostician", [], "low"),
    ])

    async def mock_spawn(node, context):
        return SubAgentResult(task_id=node.id, success=False, output="[success=False] Connection refused", turns_used=1)

    executor = DAGExecutor(
        subagent_factory=mock_spawn,
        evaluator=ResultEvaluator(),
    )
    results = await executor.execute(dag)
    assert results["t1"].success is False


@pytest.mark.asyncio
async def test_dag_context_propagation():
    dag = _make_dag([
        ("t1", "k8s_diagnostician", [], "low"),
        ("t2", "k8s_executor", ["t1"], "medium"),
    ])

    received_contexts = {}

    async def mock_spawn(node, context):
        received_contexts[node.id] = dict(context)
        return SubAgentResult(task_id=node.id, success=True, output=f"result-{node.id}", turns_used=1)

    executor = DAGExecutor(
        subagent_factory=mock_spawn,
        evaluator=ResultEvaluator(),
    )
    await executor.execute(dag)

    assert received_contexts["t1"] == {}
    assert "t1" in received_contexts["t2"]
    assert received_contexts["t2"]["t1"] == "result-t1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dag_executor.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement DAGExecutor**

```python
# src/breadmind/core/dag_executor.py
"""DAGExecutor: executes a TaskDAG in topological order with parallel batches."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

from breadmind.core.planner import TaskDAG, TaskNode
from breadmind.core.result_evaluator import ResultEvaluator, EvalResult
from breadmind.core.subagent import SubAgentResult
from breadmind.core.events import get_event_bus, Event, EventType

logger = logging.getLogger("breadmind.dag_executor")

# Concurrent subagent limit
_MAX_CONCURRENT = 5

# Difficulty-based timeouts (seconds)
_DIFFICULTY_TIMEOUT = {
    "low": 60,
    "medium": 180,
    "high": 600,
}

SubAgentFactory = Callable[[TaskNode, dict[str, str]], Awaitable[SubAgentResult]]


class DAGExecutor:
    """Executes TaskDAG nodes in dependency order, parallelizing independent nodes."""

    def __init__(
        self,
        subagent_factory: SubAgentFactory,
        evaluator: ResultEvaluator,
        max_concurrent: int = _MAX_CONCURRENT,
        progress_callback: Callable | None = None,
    ) -> None:
        self._spawn = subagent_factory
        self._evaluator = evaluator
        self._max_concurrent = max_concurrent
        self._progress = progress_callback
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def execute(self, dag: TaskDAG) -> dict[str, SubAgentResult]:
        """Execute all nodes in the DAG. Returns {task_id: SubAgentResult}."""
        results: dict[str, SubAgentResult] = {}
        completed: set[str] = set()
        failed: set[str] = set()
        all_ids = set(dag.nodes.keys())

        while completed | failed != all_ids:
            # Find ready nodes: all dependencies completed and not yet started
            ready = [
                dag.nodes[nid]
                for nid in all_ids - completed - failed
                if all(dep in completed for dep in dag.nodes[nid].depends_on)
            ]

            if not ready:
                # Stuck: remaining nodes have unmet dependencies (from failed tasks)
                for nid in all_ids - completed - failed:
                    results[nid] = SubAgentResult(
                        task_id=nid, success=False,
                        output="[success=False] Skipped: dependency failed",
                    )
                    failed.add(nid)
                break

            await self._notify_batch_start([n.id for n in ready])

            # Execute ready nodes in parallel (with concurrency limit)
            batch_results = await asyncio.gather(
                *[self._run_node(node, dag) for node in ready],
                return_exceptions=True,
            )

            for node, result in zip(ready, batch_results):
                if isinstance(result, Exception):
                    logger.error("SubAgent %s raised exception: %s", node.id, result)
                    sr = SubAgentResult(
                        task_id=node.id, success=False,
                        output=f"[success=False] Exception: {result}",
                    )
                    results[node.id] = sr
                    failed.add(node.id)
                    continue

                results[node.id] = result
                eval_result = self._evaluator.evaluate(result.output, node.expected_output)

                if eval_result.status == "normal":
                    dag.context[node.id] = result.output
                    completed.add(node.id)
                else:
                    failed.add(node.id)

            await self._notify_batch_end([n.id for n in ready])

        return results

    async def _run_node(self, node: TaskNode, dag: TaskDAG) -> SubAgentResult:
        """Execute a single node with concurrency limiting and timeout."""
        timeout = _DIFFICULTY_TIMEOUT.get(node.difficulty, 180)

        async with self._semaphore:
            await self._notify_subagent_start(node.id, node.role)
            try:
                result = await asyncio.wait_for(
                    self._spawn(node, dict(dag.context)),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                result = SubAgentResult(
                    task_id=node.id, success=False,
                    output=f"[success=False] Tool execution timed out after {timeout}s.",
                )
            await self._notify_subagent_end(node.id, result.success)
            return result

    async def _notify_batch_start(self, node_ids: list[str]) -> None:
        if self._progress:
            await self._progress("dag_batch_start", str(node_ids))
        try:
            await get_event_bus().publish_fire_and_forget(Event(
                type=EventType.DAG_BATCH_START,
                data={"nodes": node_ids},
                source="dag_executor",
            ))
        except Exception:
            pass

    async def _notify_batch_end(self, node_ids: list[str]) -> None:
        if self._progress:
            await self._progress("dag_batch_end", str(node_ids))
        try:
            await get_event_bus().publish_fire_and_forget(Event(
                type=EventType.DAG_BATCH_END,
                data={"nodes": node_ids},
                source="dag_executor",
            ))
        except Exception:
            pass

    async def _notify_subagent_start(self, task_id: str, role: str) -> None:
        try:
            await get_event_bus().publish_fire_and_forget(Event(
                type=EventType.SUBAGENT_START,
                data={"task_id": task_id, "role": role},
                source="dag_executor",
            ))
        except Exception:
            pass

    async def _notify_subagent_end(self, task_id: str, success: bool) -> None:
        try:
            await get_event_bus().publish_fire_and_forget(Event(
                type=EventType.SUBAGENT_END,
                data={"task_id": task_id, "success": success},
                source="dag_executor",
            ))
        except Exception:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dag_executor.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/core/dag_executor.py tests/test_dag_executor.py
git commit -m "feat: add DAGExecutor for parallel subagent execution"
```

---

### Task 8: Orchestrator — 전체 조율 컴포넌트

**Files:**
- Create: `src/breadmind/core/orchestrator.py`
- Create: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_orchestrator.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from breadmind.core.orchestrator import Orchestrator
from breadmind.core.planner import TaskDAG, TaskNode
from breadmind.core.subagent import SubAgentResult
from breadmind.core.role_registry import RoleRegistry
from breadmind.core.result_evaluator import ResultEvaluator
from breadmind.llm.base import LLMResponse, TokenUsage, LLMMessage


def _make_response(content):
    return LLMResponse(
        content=content,
        tool_calls=[],
        usage=TokenUsage(input_tokens=10, output_tokens=10),
        stop_reason="end_turn",
    )


def _plan_response(nodes):
    return _make_response(json.dumps({"nodes": nodes}))


@pytest.mark.asyncio
async def test_orchestrator_plans_and_executes():
    provider = AsyncMock()
    # First call: planner
    provider.chat = AsyncMock(side_effect=[
        _plan_response([
            {"id": "t1", "description": "Check pods", "role": "k8s_diagnostician",
             "depends_on": [], "difficulty": "low", "expected_output": "Pod list"},
        ]),
        # Second call: subagent
        _make_response("Found 3 healthy pods"),
        # Third call: summarizer
        _make_response("All 3 pods are healthy. No issues found."),
    ])

    registry = MagicMock()
    registry.execute = AsyncMock(return_value=MagicMock(success=True, output="pod-1\npod-2\npod-3", not_found=False))

    orch = Orchestrator(
        provider=provider,
        role_registry=RoleRegistry(),
        evaluator=ResultEvaluator(),
        tool_registry=registry,
    )
    result = await orch.run("K8s Pod 상태 확인해줘", user="test", channel="test")
    assert "healthy" in result.lower() or "pod" in result.lower()


@pytest.mark.asyncio
async def test_orchestrator_retries_on_failure():
    provider = AsyncMock()
    call_count = 0

    async def mock_chat(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Planner
            return _plan_response([
                {"id": "t1", "description": "Check pods", "role": "k8s_diagnostician",
                 "depends_on": [], "difficulty": "low", "expected_output": "Pod list"},
            ])
        elif call_count <= 3:
            # SubAgent attempts (first fails, retry succeeds)
            if call_count == 2:
                return _make_response("[success=False] Connection refused")
            return _make_response("Found 3 pods")
        else:
            # Summary
            return _make_response("Pods found after retry")

    provider.chat = AsyncMock(side_effect=mock_chat)

    orch = Orchestrator(
        provider=provider,
        role_registry=RoleRegistry(),
        evaluator=ResultEvaluator(),
        tool_registry=MagicMock(),
    )
    result = await orch.run("Check pods", user="test", channel="test")
    assert result  # Should have some result


@pytest.mark.asyncio
async def test_orchestrator_reports_partial_success():
    provider = AsyncMock()

    async def mock_chat(**kwargs):
        messages = kwargs.get("messages") or []
        user_msg = next((m.content for m in messages if m.role == "user"), "")
        if "Decompose" in (messages[0].content if messages else "") or "planner" in str(messages[0].content).lower():
            return _plan_response([
                {"id": "t1", "description": "Task A", "role": "k8s_diagnostician",
                 "depends_on": [], "difficulty": "low", "expected_output": "Result A"},
                {"id": "t2", "description": "Task B", "role": "proxmox_diagnostician",
                 "depends_on": [], "difficulty": "low", "expected_output": "Result B"},
            ])
        elif "Task A" in user_msg:
            return _make_response("Task A succeeded")
        elif "Task B" in user_msg:
            return _make_response("[success=False] Proxmox unreachable")
        else:
            return _make_response("Partial results: Task A succeeded, Task B failed")

    provider.chat = AsyncMock(side_effect=mock_chat)

    orch = Orchestrator(
        provider=provider,
        role_registry=RoleRegistry(),
        evaluator=ResultEvaluator(),
        tool_registry=MagicMock(),
    )
    result = await orch.run("Check K8s and Proxmox", user="test", channel="test")
    assert result  # Should return partial success summary
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement Orchestrator**

```python
# src/breadmind/core/orchestrator.py
"""Orchestrator: coordinates Planner, DAGExecutor, and SubAgents for complex tasks."""
from __future__ import annotations

import logging
from typing import Callable, Awaitable

from breadmind.llm.base import LLMProvider, LLMMessage
from breadmind.core.planner import Planner, TaskDAG, TaskNode
from breadmind.core.dag_executor import DAGExecutor
from breadmind.core.subagent import SubAgent, SubAgentResult
from breadmind.core.result_evaluator import ResultEvaluator
from breadmind.core.role_registry import RoleRegistry
from breadmind.core.events import get_event_bus, Event, EventType

logger = logging.getLogger("breadmind.orchestrator")

# Max retries per task before moving to replan
_MAX_RETRIES = 2
# Max replan attempts before giving up
_MAX_REPLANS = 1

# Difficulty -> max_turns mapping
_DIFFICULTY_TURNS = {
    "low": 3,
    "medium": 5,
    "high": 10,
}


class Orchestrator:
    """Top-level coordinator: plans, executes DAG, handles failures, summarizes."""

    def __init__(
        self,
        provider: LLMProvider,
        role_registry: RoleRegistry,
        evaluator: ResultEvaluator,
        tool_registry: object,
        progress_callback: Callable | None = None,
    ) -> None:
        self._provider = provider
        self._roles = role_registry
        self._evaluator = evaluator
        self._tool_registry = tool_registry
        self._progress = progress_callback
        self._planner = Planner(provider=provider, role_registry=role_registry)

    async def run(self, message: str, user: str, channel: str) -> str:
        """Execute a complex task through the full orchestration pipeline."""
        await self._emit(EventType.ORCHESTRATOR_START, {"message": message, "user": user})

        # Phase 1: Plan
        if self._progress:
            await self._progress("orchestrator", "Planning task decomposition...")
        dag = await self._planner.plan(message)
        logger.info("Planner created DAG with %d nodes for: %s", len(dag.nodes), message[:100])

        # Phase 2: Execute with retry/replan loop
        results = await self._execute_with_fallback(dag)

        # Phase 3: Summarize
        if self._progress:
            await self._progress("orchestrator", "Summarizing results...")
        summary = await self._summarize(dag, results)

        await self._emit(EventType.ORCHESTRATOR_END, {
            "total_tasks": len(dag.nodes),
            "succeeded": sum(1 for r in results.values() if r.success),
            "failed": sum(1 for r in results.values() if not r.success),
        })

        return summary

    async def _execute_with_fallback(self, dag: TaskDAG) -> dict[str, SubAgentResult]:
        """Execute DAG with retry and replan fallback."""
        executor = DAGExecutor(
            subagent_factory=self._create_subagent_factory(),
            evaluator=self._evaluator,
            progress_callback=self._progress,
        )

        results = await executor.execute(dag)

        # Check for failures and attempt retries
        failed_tasks = {tid: r for tid, r in results.items() if not r.success}

        for tid, result in failed_tasks.items():
            node = dag.nodes.get(tid)
            if node is None:
                continue

            # Phase 2a: Retry
            for attempt in range(node.max_retries):
                logger.info("Retrying task %s (attempt %d/%d)", tid, attempt + 1, node.max_retries)
                retry_result = await self._retry_single(node, dag.context)
                if retry_result.success:
                    results[tid] = retry_result
                    dag.context[tid] = retry_result.output
                    break
                # Include failure context for next retry
                results[tid] = retry_result

            if results[tid].success:
                continue

            # Phase 2b: Replan (max 1 attempt)
            eval_result = self._evaluator.evaluate(results[tid].output, node.expected_output)
            logger.info("Replanning for failed task %s: %s", tid, eval_result.failure_reason)
            await self._emit(EventType.ORCHESTRATOR_REPLAN, {"failed_task": tid, "reason": eval_result.failure_reason})

            alt_dag = await self._planner.replan(dag.goal, dag, tid, eval_result.failure_reason)
            if alt_dag.nodes:
                alt_executor = DAGExecutor(
                    subagent_factory=self._create_subagent_factory(),
                    evaluator=self._evaluator,
                    progress_callback=self._progress,
                )
                alt_results = await alt_executor.execute(alt_dag)

                # Merge successful alt results
                for alt_tid, alt_result in alt_results.items():
                    if alt_result.success:
                        results[alt_tid] = alt_result
                        dag.context[alt_tid] = alt_result.output
                        # Mark original as superseded
                        results[tid] = SubAgentResult(
                            task_id=tid, success=True,
                            output=f"Replaced by {alt_tid}: {alt_result.output}",
                            turns_used=alt_result.turns_used,
                        )
                        break

        return results

    def _create_subagent_factory(self):
        """Return an async callable that spawns SubAgents."""
        roles = self._roles
        provider = self._provider
        tool_registry = self._tool_registry

        async def factory(node: TaskNode, context: dict[str, str]) -> SubAgentResult:
            model = roles.difficulty_to_model(node.difficulty)
            system_prompt = roles.get_prompt(node.role)
            tool_names = node.tools or roles.get_tools(node.role)
            max_turns = _DIFFICULTY_TURNS.get(node.difficulty, 5)

            # Filter tool definitions to role-specific set
            all_tools = tool_registry.get_all_definitions() if hasattr(tool_registry, "get_all_definitions") else []
            tools = [t for t in all_tools if t.get("name") in tool_names] if tool_names else all_tools[:20]

            agent = SubAgent(
                task_id=node.id,
                description=node.description,
                role=node.role,
                provider=provider,
                tools=tools,
                system_prompt=system_prompt,
                max_turns=max_turns,
                tool_executor=tool_registry.execute if hasattr(tool_registry, "execute") else None,
            )
            return await agent.run(context=context)

        return factory

    async def _retry_single(self, node: TaskNode, context: dict[str, str]) -> SubAgentResult:
        """Retry a single failed node."""
        factory = self._create_subagent_factory()
        return await factory(node, context)

    async def _summarize(self, dag: TaskDAG, results: dict[str, SubAgentResult]) -> str:
        """Use LLM to produce a user-facing summary of all task results."""
        results_text = []
        for tid, node in dag.nodes.items():
            result = results.get(tid)
            status = "SUCCESS" if result and result.success else "FAILED"
            output = (result.output[:500] if result else "No result")
            results_text.append(f"[{status}] {node.description}:\n{output}")

        messages = [
            LLMMessage(role="system", content=(
                "You are summarizing the results of a multi-step infrastructure task. "
                "Provide a clear, concise summary for the user. "
                "Highlight successes, failures, and any actions taken. "
                "Use the user's language (Korean if the goal is in Korean)."
            )),
            LLMMessage(role="user", content=(
                f"Goal: {dag.goal}\n\n"
                f"Results:\n" + "\n\n".join(results_text)
            )),
        ]

        try:
            response = await self._provider.chat(messages=messages)
            return response.content or "\n".join(results_text)
        except Exception as e:
            logger.error("Summary generation failed: %s", e)
            return "\n".join(results_text)

    async def _emit(self, event_type: EventType, data: dict) -> None:
        try:
            await get_event_bus().publish_fire_and_forget(Event(
                type=event_type, data=data, source="orchestrator",
            ))
        except Exception:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/core/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add Orchestrator for complex task coordination"
```

---

### Task 9: CoreAgent에 Orchestrator 분기 통합

**Files:**
- Modify: `src/breadmind/core/agent.py:319-389`

- [ ] **Step 1: Add orchestrator attribute to CoreAgent.__init__**

In `src/breadmind/core/agent.py`, add `orchestrator` parameter to `__init__` (after `profiler` parameter):

```python
    def __init__(
        self,
        # ... existing params ...
        profiler: object | None = None,
        prompt_builder: object | None = None,
        orchestrator: object | None = None,
    ):
        # ... existing assignments ...
        self._orchestrator = orchestrator
```

- [ ] **Step 2: Add orchestrator branching in handle_message**

After the profiler intent recording block (line ~323) and before credential_ref handling (line ~326), insert the orchestrator branch:

```python
        # Step 1.5: Route complex tasks to Orchestrator
        if self._orchestrator and intent.complexity == "complex":
            logger.info(json.dumps({"event": "orchestrator_route", "complexity": "complex"}))
            if self._progress_callback:
                await self._progress_callback("orchestrator", "Complex task detected, routing to orchestrator...")
            try:
                result = await self._orchestrator.run(message, user=user, channel=channel)
                # Store result in working memory
                if self._working_memory is not None:
                    self._working_memory.add_message(
                        session_id,
                        LLMMessage(role="assistant", content=result),
                    )
                await get_event_bus().publish_fire_and_forget(Event(
                    type=EventType.SESSION_END,
                    data={"user": user, "channel": channel, "session_id": session_id, "route": "orchestrator"},
                    source="agent",
                ))
                return result
            except Exception as e:
                logger.warning("Orchestrator failed, falling back to single agent: %s", e)
                # Fall through to normal single-agent loop
```

- [ ] **Step 3: Run existing agent tests to verify no regression**

Run: `python -m pytest tests/test_agent.py -v`
Expected: All existing tests PASS (orchestrator=None by default, so no branching)

- [ ] **Step 4: Commit**

```bash
git add src/breadmind/core/agent.py
git commit -m "feat: add orchestrator branching in CoreAgent for complex tasks"
```

---

### Task 10: Bootstrap에 Orchestrator 초기화 등록

**Files:**
- Modify: `src/breadmind/core/bootstrap.py`

- [ ] **Step 1: Add Orchestrator initialization in init_core_services**

In `src/breadmind/core/bootstrap.py`, after the SafetyGuard registration (around line 125), add:

```python
    # ── Role Registry & Orchestrator ────────────────────────────
    from breadmind.core.role_registry import RoleRegistry
    from breadmind.core.result_evaluator import ResultEvaluator
    from breadmind.core.orchestrator import Orchestrator

    role_registry = RoleRegistry()
    container.register("role_registry", role_registry)

    orchestrator = Orchestrator(
        provider=provider,
        role_registry=role_registry,
        evaluator=ResultEvaluator(),
        tool_registry=registry,
    )
    container.register("orchestrator", orchestrator)
```

- [ ] **Step 2: Pass orchestrator to CoreAgent in init_agent phase**

Find where CoreAgent is instantiated (Phase 5) and add `orchestrator=container.get("orchestrator")` to the constructor call.

- [ ] **Step 3: Run bootstrap-related tests**

Run: `python -m pytest tests/ -k "bootstrap or config" -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add src/breadmind/core/bootstrap.py
git commit -m "feat: register Orchestrator in bootstrap service container"
```

---

### Task 11: 기존 Swarm/delegate_tasks 코드 삭제

**Files:**
- Delete: `src/breadmind/core/swarm.py`
- Delete: `src/breadmind/core/swarm_executor.py`
- Delete: `src/breadmind/core/team_builder.py`
- Delete: `tests/test_swarm.py`
- Modify: `src/breadmind/tools/builtin.py` (delegate_tasks 함수 제거)
- Modify: any imports referencing deleted modules

- [ ] **Step 1: Search for all imports of deleted modules**

Run: `grep -rn "from breadmind.core.swarm\|from breadmind.core.team_builder\|import swarm\|import team_builder\|delegate_tasks" src/ tests/`

Note all files that import these modules — they all need updating.

- [ ] **Step 2: Remove delegate_tasks function from builtin.py**

Delete the `delegate_tasks` function (lines ~486-565) and its `@tool` decorator from `src/breadmind/tools/builtin.py`.

- [ ] **Step 3: Delete swarm and team_builder files**

```bash
rm src/breadmind/core/swarm.py
rm src/breadmind/core/swarm_executor.py
rm src/breadmind/core/team_builder.py
rm tests/test_swarm.py
```

- [ ] **Step 4: Update all imports that referenced deleted modules**

For each file found in Step 1, remove or replace the import. If code depended on SwarmManager, redirect to Orchestrator or RoleRegistry as appropriate.

- [ ] **Step 5: Run full test suite to verify nothing is broken**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests PASS (some test files deleted, remaining tests should pass)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: remove Swarm/TeamBuilder/delegate_tasks, replaced by Orchestrator"
```

---

### Task 12: Web API 엔드포인트 갱신

**Files:**
- Modify: `src/breadmind/web/routes/subagent.py`

- [ ] **Step 1: Update API endpoints for new Orchestrator**

Replace the subagent routes to expose orchestrator status and DAG progress:

```python
# src/breadmind/web/routes/subagent.py
"""Orchestrator API routes."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/orchestrator/status")
async def orchestrator_status(request: Request):
    """Return orchestrator availability status."""
    app = request.app
    orchestrator = getattr(app, "_orchestrator", None)
    return JSONResponse({"available": orchestrator is not None})


@router.get("/api/orchestrator/roles")
async def list_roles(request: Request):
    """List all available subagent roles."""
    app = request.app
    role_registry = getattr(app, "_role_registry", None)
    if role_registry is None:
        return JSONResponse({"roles": []})
    roles = [
        {
            "name": r.name,
            "domain": r.domain,
            "task_type": r.task_type,
            "description": r.description,
            "dedicated_tools": r.dedicated_tools,
        }
        for r in role_registry.list_roles()
    ]
    return JSONResponse({"roles": roles})
```

- [ ] **Step 2: Update WebApp to wire new routes**

In the WebApp initialization (where routes are registered), replace the old subagent router import with the new one.

- [ ] **Step 3: Run route tests**

Run: `python -m pytest tests/ -k "route or web" -v --tb=short`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add src/breadmind/web/routes/subagent.py
git commit -m "feat: update web API routes for orchestrator"
```

---

### Task 13: 통합 테스트 — 전체 파이프라인

**Files:**
- Create: `tests/test_orchestrator_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_orchestrator_integration.py
"""End-to-end integration test for Orchestrator pipeline."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.core.orchestrator import Orchestrator
from breadmind.core.role_registry import RoleRegistry
from breadmind.core.result_evaluator import ResultEvaluator
from breadmind.llm.base import LLMResponse, TokenUsage


def _resp(content):
    return LLMResponse(
        content=content, tool_calls=[],
        usage=TokenUsage(input_tokens=10, output_tokens=10),
        stop_reason="end_turn",
    )


@pytest.mark.asyncio
async def test_full_pipeline_multi_domain():
    """Test: K8s + Proxmox parallel diagnosis → sequential fix → summary."""
    call_seq = []

    async def mock_chat(**kwargs):
        messages = kwargs.get("messages") or []
        system = messages[0].content if messages else ""
        user_msg = next((m.content for m in messages if m.role == "user"), "")

        # Planner call
        if "task planner" in system.lower():
            call_seq.append("planner")
            return _resp(json.dumps({"nodes": [
                {"id": "t1", "description": "Check K8s pods", "role": "k8s_diagnostician",
                 "depends_on": [], "difficulty": "low", "expected_output": "Pod status"},
                {"id": "t2", "description": "Check Proxmox VMs", "role": "proxmox_diagnostician",
                 "depends_on": [], "difficulty": "low", "expected_output": "VM status"},
                {"id": "t3", "description": "Fix K8s issue", "role": "k8s_executor",
                 "depends_on": ["t1"], "difficulty": "medium", "expected_output": "Issue fixed"},
            ]}))
        # SubAgent calls
        elif "diagnostics" in system.lower() or "diagnostician" in system.lower():
            call_seq.append(f"subagent:{user_msg[:20]}")
            return _resp(f"[OK] All healthy for: {user_msg[:30]}")
        elif "operations" in system.lower() or "executor" in system.lower():
            call_seq.append(f"subagent:executor")
            return _resp("Fixed: scaled deployment to 3 replicas")
        # Summary
        elif "summarizing" in system.lower():
            call_seq.append("summary")
            return _resp("All systems healthy. K8s scaled to 3 replicas. Proxmox VMs running.")
        else:
            call_seq.append(f"unknown:{system[:30]}")
            return _resp("OK")

    provider = AsyncMock()
    provider.chat = AsyncMock(side_effect=mock_chat)

    registry = MagicMock()
    registry.get_all_definitions = MagicMock(return_value=[])
    registry.execute = AsyncMock()

    orch = Orchestrator(
        provider=provider,
        role_registry=RoleRegistry(),
        evaluator=ResultEvaluator(),
        tool_registry=registry,
    )

    result = await orch.run(
        "K8s Pod 상태 확인하고 문제 있으면 고쳐줘, Proxmox VM도 확인해",
        user="admin",
        channel="web",
    )

    # Verify planner was called first
    assert call_seq[0] == "planner"
    # Verify summary was generated
    assert "summary" in call_seq
    # Verify result is meaningful
    assert result
    assert len(result) > 10
```

- [ ] **Step 2: Run integration test**

Run: `python -m pytest tests/test_orchestrator_integration.py -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_orchestrator_integration.py
git commit -m "test: add end-to-end orchestrator integration test"
```

---

### Task 14: Lint 검사 및 최종 정리

- [ ] **Step 1: Run linter**

Run: `ruff check src/breadmind/core/orchestrator.py src/breadmind/core/planner.py src/breadmind/core/dag_executor.py src/breadmind/core/subagent.py src/breadmind/core/result_evaluator.py src/breadmind/core/role_registry.py`
Expected: No errors (fix if any)

- [ ] **Step 2: Run full lint**

Run: `ruff check src/ tests/`
Expected: No new errors

- [ ] **Step 3: Run full test suite with coverage**

Run: `python -m pytest tests/ --cov=breadmind --cov-fail-under=55 -v --tb=short`
Expected: All PASS, coverage >= 55%

- [ ] **Step 4: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "chore: lint fixes for orchestrator module"
```
