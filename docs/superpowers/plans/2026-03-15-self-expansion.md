# Self-Expansion System Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BreadMind에 자기 확장 시스템을 추가하여 성능 추적, skill 저장, 도구 부족 자동 감지, 팀 자동 구성을 가능하게 한다.

**Architecture:** 4개의 계층적 컴포넌트(PerformanceTracker → SkillStore → ToolGapDetector → TeamBuilder)를 하위→상위 순서로 구현. 각 컴포넌트는 독립 파일에 단일 책임을 가지며, 하위 계층을 참조한다.

**Tech Stack:** Python 3.12+, asyncio, dataclasses, DB persistence via settings table (JSONB)

**Spec:** `docs/superpowers/specs/2026-03-15-self-expansion-design.md`

---

## Chunk 1: PerformanceTracker + ToolResult.not_found

### Task 1: ToolResult에 not_found 필드 추가

**Files:**
- Modify: `src/breadmind/tools/registry.py:13-16` (ToolResult dataclass)
- Modify: `src/breadmind/tools/registry.py:259` (execute() return)
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing test for ToolResult.not_found**

```python
# tests/test_tools.py — 기존 파일에 추가
@pytest.mark.asyncio
async def test_execute_unknown_tool_sets_not_found():
    registry = ToolRegistry()
    result = await registry.execute("nonexistent_tool", {})
    assert result.success is False
    assert result.not_found is True
    assert "nonexistent_tool" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_tools.py::test_execute_unknown_tool_sets_not_found -v`
Expected: FAIL — `AttributeError: 'ToolResult' has no attribute 'not_found'`

- [ ] **Step 3: Add not_found field to ToolResult**

In `src/breadmind/tools/registry.py:13-16`, change:
```python
@dataclass
class ToolResult:
    success: bool
    output: str
    not_found: bool = False
```

In `src/breadmind/tools/registry.py:259`, change the return to:
```python
return ToolResult(success=False, output=f"Tool not found: {name}", not_found=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_tools.py::test_execute_unknown_tool_sets_not_found -v`
Expected: PASS

- [ ] **Step 5: Run all existing tests to verify no regression**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_tools.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/breadmind/tools/registry.py tests/test_tools.py
git commit -m "feat: add not_found field to ToolResult for structured tool gap detection"
```

---

### Task 2: PerformanceTracker 핵심 구현

**Files:**
- Create: `src/breadmind/core/performance.py`
- Create: `tests/test_performance.py`

- [ ] **Step 1: Write failing tests for PerformanceTracker**

```python
# tests/test_performance.py
import pytest
from datetime import datetime, timezone
from breadmind.core.performance import PerformanceTracker, RoleStats, TaskRecord


class TestTaskRecord:
    def test_create_task_record(self):
        record = TaskRecord(
            role="k8s_expert",
            task_description="Check pod health",
            success=True,
            duration_ms=1500.0,
            result_summary="All pods healthy",
        )
        assert record.role == "k8s_expert"
        assert record.success is True
        assert record.timestamp is not None


class TestRoleStats:
    def test_success_rate_no_runs(self):
        stats = RoleStats(role="test")
        assert stats.success_rate == 0.0

    def test_success_rate_with_runs(self):
        stats = RoleStats(role="test", total_runs=10, successes=7, failures=3)
        assert stats.success_rate == 0.7

    def test_avg_duration(self):
        stats = RoleStats(role="test", total_runs=4, total_duration_ms=2000.0)
        assert stats.avg_duration_ms == 500.0


class TestPerformanceTracker:
    @pytest.mark.asyncio
    async def test_record_and_get_stats(self):
        tracker = PerformanceTracker()
        await tracker.record_task_result(
            role="k8s_expert",
            task_desc="Check pods",
            success=True,
            duration_ms=1200.0,
            result_summary="OK",
        )
        stats = tracker.get_role_stats("k8s_expert")
        assert stats is not None
        assert stats.total_runs == 1
        assert stats.successes == 1
        assert stats.success_rate == 1.0

    @pytest.mark.asyncio
    async def test_record_failure(self):
        tracker = PerformanceTracker()
        await tracker.record_task_result("test_role", "task", False, 500.0, "Error")
        stats = tracker.get_role_stats("test_role")
        assert stats.failures == 1
        assert stats.success_rate == 0.0

    @pytest.mark.asyncio
    async def test_get_underperforming_roles(self):
        tracker = PerformanceTracker()
        await tracker.record_task_result("good_role", "t1", True, 100.0, "ok")
        await tracker.record_task_result("bad_role", "t2", False, 100.0, "err")
        await tracker.record_task_result("bad_role", "t3", False, 100.0, "err")
        under = tracker.get_underperforming_roles(threshold=0.5)
        assert len(under) == 1
        assert under[0].role == "bad_role"

    @pytest.mark.asyncio
    async def test_record_feedback(self):
        tracker = PerformanceTracker()
        await tracker.record_task_result("role_a", "task", True, 100.0, "ok")
        await tracker.record_feedback("role_a", "good", "Great analysis")
        stats = tracker.get_role_stats("role_a")
        assert len(stats.feedback_history) == 1
        assert stats.feedback_history[0]["rating"] == "good"

    @pytest.mark.asyncio
    async def test_get_all_stats(self):
        tracker = PerformanceTracker()
        await tracker.record_task_result("role_a", "t1", True, 100.0, "ok")
        await tracker.record_task_result("role_b", "t2", True, 200.0, "ok")
        all_stats = tracker.get_all_stats()
        assert "role_a" in all_stats
        assert "role_b" in all_stats

    @pytest.mark.asyncio
    async def test_get_top_roles(self):
        tracker = PerformanceTracker()
        await tracker.record_task_result("role_a", "t1", True, 100.0, "ok")
        await tracker.record_task_result("role_a", "t2", True, 100.0, "ok")
        await tracker.record_task_result("role_b", "t1", True, 100.0, "ok")
        await tracker.record_task_result("role_b", "t2", False, 100.0, "err")
        top = tracker.get_top_roles(limit=1)
        assert len(top) == 1
        assert top[0].role == "role_a"

    @pytest.mark.asyncio
    async def test_recent_records_cap_at_100(self):
        tracker = PerformanceTracker()
        for i in range(110):
            await tracker.record_task_result("busy_role", f"task_{i}", True, 10.0, "ok")
        stats = tracker.get_role_stats("busy_role")
        assert len(stats.recent_records) == 100
        assert stats.total_runs == 110

    @pytest.mark.asyncio
    async def test_export_import(self):
        tracker = PerformanceTracker()
        await tracker.record_task_result("role_a", "t1", True, 100.0, "ok")
        data = tracker.export_stats()
        tracker2 = PerformanceTracker()
        tracker2.import_stats(data)
        stats = tracker2.get_role_stats("role_a")
        assert stats is not None
        assert stats.total_runs == 1

    @pytest.mark.asyncio
    async def test_suggest_improvements(self):
        tracker = PerformanceTracker()
        await tracker.record_task_result("bad_role", "t1", False, 100.0, "Connection timeout")
        await tracker.record_task_result("bad_role", "t2", False, 100.0, "Permission denied")

        async def mock_handler(msg, user="", channel=""):
            return "Suggestion: Add retry logic and check permissions."

        result = await tracker.suggest_improvements("bad_role", mock_handler)
        assert "Suggestion" in result or "retry" in result.lower()

    @pytest.mark.asyncio
    async def test_suggest_improvements_no_data(self):
        tracker = PerformanceTracker()
        result = await tracker.suggest_improvements("unknown", None)
        assert "No data" in result

    @pytest.mark.asyncio
    async def test_concurrent_recording(self):
        import asyncio
        tracker = PerformanceTracker()
        tasks = [
            tracker.record_task_result(f"role_{i % 3}", f"task_{i}", i % 2 == 0, 10.0, "ok")
            for i in range(30)
        ]
        await asyncio.gather(*tasks)
        total = sum(s.total_runs for s in tracker.get_all_stats().values())
        assert total == 30
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_performance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'breadmind.core.performance'`

- [ ] **Step 3: Implement PerformanceTracker**

Create `src/breadmind/core/performance.py`:
```python
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from breadmind.storage.database import Database

logger = logging.getLogger(__name__)

_MAX_RECENT_RECORDS = 100


@dataclass
class TaskRecord:
    role: str
    task_description: str
    success: bool
    duration_ms: float
    result_summary: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RoleStats:
    role: str
    total_runs: int = 0
    successes: int = 0
    failures: int = 0
    total_duration_ms: float = 0.0
    recent_records: list[TaskRecord] = field(default_factory=list)
    feedback_history: list[dict] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.successes / self.total_runs

    @property
    def avg_duration_ms(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.total_duration_ms / self.total_runs


class PerformanceTracker:
    """Tracks execution performance of swarm roles and skills."""

    def __init__(self, db: Database | None = None):
        self._db = db
        self._stats: dict[str, RoleStats] = {}
        self._lock = asyncio.Lock()

    async def record_task_result(
        self,
        role: str,
        task_desc: str,
        success: bool,
        duration_ms: float,
        result_summary: str,
    ) -> None:
        async with self._lock:
            stats = self._stats.setdefault(role, RoleStats(role=role))
            stats.total_runs += 1
            if success:
                stats.successes += 1
            else:
                stats.failures += 1
            stats.total_duration_ms += duration_ms

            record = TaskRecord(
                role=role,
                task_description=task_desc,
                success=success,
                duration_ms=duration_ms,
                result_summary=result_summary,
            )
            stats.recent_records.append(record)
            if len(stats.recent_records) > _MAX_RECENT_RECORDS:
                stats.recent_records = stats.recent_records[-_MAX_RECENT_RECORDS:]

    async def record_feedback(
        self, role: str, rating: str, comment: str
    ) -> None:
        async with self._lock:
            stats = self._stats.get(role)
            if stats is None:
                stats = RoleStats(role=role)
                self._stats[role] = stats
            stats.feedback_history.append({
                "rating": rating,
                "comment": comment,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    def get_role_stats(self, role: str) -> RoleStats | None:
        return self._stats.get(role)

    def get_all_stats(self) -> dict[str, RoleStats]:
        return dict(self._stats)

    def get_underperforming_roles(self, threshold: float = 0.5) -> list[RoleStats]:
        return [
            s for s in self._stats.values()
            if s.total_runs > 0 and s.success_rate < threshold
        ]

    def get_top_roles(self, limit: int = 5) -> list[RoleStats]:
        ranked = sorted(
            [s for s in self._stats.values() if s.total_runs > 0],
            key=lambda s: (s.success_rate, s.total_runs),
            reverse=True,
        )
        return ranked[:limit]

    async def suggest_improvements(self, role: str, message_handler) -> str:
        stats = self._stats.get(role)
        if not stats or stats.total_runs == 0:
            return f"No data available for role '{role}'."

        failures = [r for r in stats.recent_records if not r.success]
        if not failures:
            return f"Role '{role}' has no recent failures."

        failure_summaries = "\n".join(
            f"- Task: {r.task_description} | Error: {r.result_summary}"
            for r in failures[:10]
        )
        prompt = (
            f"Analyze failure patterns for the '{role}' role.\n\n"
            f"Stats: {stats.total_runs} total, {stats.successes} successes, "
            f"{stats.failures} failures ({stats.success_rate:.0%} success rate)\n\n"
            f"Recent failures:\n{failure_summaries}\n\n"
            f"Suggest specific improvements to the role's system prompt to reduce failures. "
            f"Be concise and actionable."
        )
        try:
            if asyncio.iscoroutinefunction(message_handler):
                return await message_handler(
                    prompt, user="performance_tracker", channel="system:performance"
                )
            return message_handler(
                prompt, user="performance_tracker", channel="system:performance"
            )
        except Exception as e:
            logger.error(f"Failed to generate improvement suggestions: {e}")
            return f"Error generating suggestions: {e}"

    def export_stats(self) -> dict:
        result = {}
        for role, stats in self._stats.items():
            result[role] = {
                "total_runs": stats.total_runs,
                "successes": stats.successes,
                "failures": stats.failures,
                "total_duration_ms": stats.total_duration_ms,
                "feedback_history": stats.feedback_history,
            }
        return result

    def import_stats(self, data: dict) -> None:
        self._stats.clear()
        for role, d in data.items():
            self._stats[role] = RoleStats(
                role=role,
                total_runs=d.get("total_runs", 0),
                successes=d.get("successes", 0),
                failures=d.get("failures", 0),
                total_duration_ms=d.get("total_duration_ms", 0.0),
                feedback_history=d.get("feedback_history", []),
            )

    async def flush_to_db(self) -> None:
        if self._db:
            try:
                await self._db.set_setting("performance_stats", self.export_stats())
            except Exception as e:
                logger.error(f"Failed to flush performance stats: {e}")

    async def load_from_db(self) -> None:
        if self._db:
            try:
                data = await self._db.get_setting("performance_stats")
                if data:
                    self.import_stats(data)
            except Exception as e:
                logger.error(f"Failed to load performance stats: {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_performance.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/core/performance.py tests/test_performance.py
git commit -m "feat: add PerformanceTracker for role/skill execution metrics"
```

---

## Chunk 2: SkillStore

### Task 3: SkillStore 핵심 구현

**Files:**
- Create: `src/breadmind/core/skill_store.py`
- Create: `tests/test_skill_store.py`

- [ ] **Step 1: Write failing tests for SkillStore**

```python
# tests/test_skill_store.py
import pytest
from breadmind.core.skill_store import SkillStore, Skill


class TestSkill:
    def test_create_skill(self):
        skill = Skill(
            name="pod_restart_check",
            description="Check and restart crashed pods",
            prompt_template="Check all pods in namespace {namespace} and restart crashed ones.",
            steps=["List pods", "Find CrashLoopBackOff", "Restart"],
            trigger_keywords=["pod", "restart", "crash"],
        )
        assert skill.name == "pod_restart_check"
        assert skill.usage_count == 0
        assert skill.source == "manual"


class TestSkillStore:
    @pytest.mark.asyncio
    async def test_add_and_get_skill(self):
        store = SkillStore()
        skill = await store.add_skill(
            name="test_skill",
            description="A test skill",
            prompt_template="Do the test thing",
            steps=["step1"],
            trigger_keywords=["test"],
            source="manual",
        )
        assert skill.name == "test_skill"
        retrieved = await store.get_skill("test_skill")
        assert retrieved is not None
        assert retrieved.description == "A test skill"

    @pytest.mark.asyncio
    async def test_list_skills(self):
        store = SkillStore()
        await store.add_skill("s1", "desc1", "prompt1", [], ["kw1"], "manual")
        await store.add_skill("s2", "desc2", "prompt2", [], ["kw2"], "manual")
        skills = await store.list_skills()
        assert len(skills) == 2

    @pytest.mark.asyncio
    async def test_update_skill(self):
        store = SkillStore()
        await store.add_skill("s1", "old desc", "old prompt", [], ["kw"], "manual")
        await store.update_skill("s1", description="new desc")
        skill = await store.get_skill("s1")
        assert skill.description == "new desc"
        assert skill.prompt_template == "old prompt"  # unchanged

    @pytest.mark.asyncio
    async def test_remove_skill(self):
        store = SkillStore()
        await store.add_skill("s1", "desc", "prompt", [], ["kw"], "manual")
        removed = await store.remove_skill("s1")
        assert removed is True
        assert await store.get_skill("s1") is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent_skill(self):
        store = SkillStore()
        removed = await store.remove_skill("nonexistent")
        assert removed is False

    @pytest.mark.asyncio
    async def test_find_matching_skills(self):
        store = SkillStore()
        await store.add_skill("pod_check", "Check pod health", "prompt", [], ["pod", "health", "kubernetes"], "manual")
        await store.add_skill("vm_check", "Check VM status", "prompt", [], ["vm", "proxmox"], "manual")
        matches = await store.find_matching_skills("pod health check")
        assert len(matches) >= 1
        assert matches[0].name == "pod_check"

    @pytest.mark.asyncio
    async def test_record_usage(self):
        store = SkillStore()
        await store.add_skill("s1", "desc", "prompt", [], ["kw"], "manual")
        await store.record_usage("s1", success=True)
        await store.record_usage("s1", success=False)
        skill = await store.get_skill("s1")
        assert skill.usage_count == 2
        assert skill.success_count == 1

    @pytest.mark.asyncio
    async def test_export_import(self):
        store = SkillStore()
        await store.add_skill("s1", "desc", "prompt", ["step1"], ["kw"], "manual")
        data = store.export_skills()
        store2 = SkillStore()
        store2.import_skills(data)
        skill = await store2.get_skill("s1")
        assert skill is not None
        assert skill.description == "desc"

    @pytest.mark.asyncio
    async def test_add_duplicate_skill_raises(self):
        store = SkillStore()
        await store.add_skill("s1", "desc", "prompt", [], ["kw"], "manual")
        with pytest.raises(ValueError, match="already exists"):
            await store.add_skill("s1", "desc2", "prompt2", [], ["kw2"], "manual")

    @pytest.mark.asyncio
    async def test_detect_patterns(self):
        store = SkillStore()
        async def mock_handler(msg, user="", channel=""):
            return "SKILL|restart_pods|Auto-restart crashed pods|kubectl get pods --field-selector status.phase=Failed|pod,restart,crash"

        recent_tasks = [
            {"role": "k8s_expert", "description": "Restart crashed pods", "success": True},
            {"role": "k8s_expert", "description": "Check pod crashes", "success": True},
        ]
        patterns = await store.detect_patterns(recent_tasks, mock_handler)
        assert len(patterns) == 1
        assert patterns[0]["name"] == "restart_pods"

    @pytest.mark.asyncio
    async def test_detect_patterns_none_found(self):
        store = SkillStore()
        async def mock_handler(msg, user="", channel=""):
            return "NONE"
        patterns = await store.detect_patterns([{"role": "a", "description": "b", "success": True}], mock_handler)
        assert patterns == []

    @pytest.mark.asyncio
    async def test_detect_patterns_no_handler(self):
        store = SkillStore()
        patterns = await store.detect_patterns([{"role": "a"}], None)
        assert patterns == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_skill_store.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement SkillStore**

Create `src/breadmind/core/skill_store.py`:
```python
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from breadmind.storage.database import Database
    from breadmind.core.performance import PerformanceTracker

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    name: str
    description: str
    prompt_template: str
    steps: list[str] = field(default_factory=list)
    trigger_keywords: list[str] = field(default_factory=list)
    usage_count: int = 0
    success_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "manual"


class SkillStore:
    """Stores and retrieves reusable workflow/prompt skills."""

    def __init__(
        self,
        db: Database | None = None,
        tracker: PerformanceTracker | None = None,
    ):
        self._db = db
        self._tracker = tracker
        self._skills: dict[str, Skill] = {}
        self._lock = asyncio.Lock()

    async def add_skill(
        self,
        name: str,
        description: str,
        prompt_template: str,
        steps: list[str],
        trigger_keywords: list[str],
        source: str = "manual",
    ) -> Skill:
        async with self._lock:
            if name in self._skills:
                raise ValueError(f"Skill '{name}' already exists")
            skill = Skill(
                name=name,
                description=description,
                prompt_template=prompt_template,
                steps=steps,
                trigger_keywords=trigger_keywords,
                source=source,
            )
            self._skills[name] = skill
            return skill

    async def update_skill(self, name: str, **kwargs) -> None:
        async with self._lock:
            skill = self._skills.get(name)
            if skill is None:
                raise ValueError(f"Skill '{name}' not found")
            for key, value in kwargs.items():
                if hasattr(skill, key) and key not in ("name", "created_at"):
                    setattr(skill, key, value)
            skill.updated_at = datetime.now(timezone.utc)

    async def remove_skill(self, name: str) -> bool:
        async with self._lock:
            return self._skills.pop(name, None) is not None

    async def get_skill(self, name: str) -> Skill | None:
        return self._skills.get(name)

    async def list_skills(self) -> list[Skill]:
        return list(self._skills.values())

    async def find_matching_skills(
        self, query: str, limit: int = 3
    ) -> list[Skill]:
        query_words = set(query.lower().split())
        scored: list[tuple[float, Skill]] = []
        for skill in self._skills.values():
            kw_set = set(k.lower() for k in skill.trigger_keywords)
            desc_words = set(skill.description.lower().split())
            kw_matches = len(query_words & kw_set)
            desc_matches = len(query_words & desc_words)
            score = kw_matches * 2.0 + desc_matches
            if score > 0:
                scored.append((score, skill))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:limit]]

    async def record_usage(self, name: str, success: bool) -> None:
        async with self._lock:
            skill = self._skills.get(name)
            if skill:
                skill.usage_count += 1
                if success:
                    skill.success_count += 1

    async def detect_patterns(
        self, recent_tasks: list[dict], message_handler
    ) -> list[dict]:
        if not recent_tasks or not message_handler:
            return []

        task_summaries = "\n".join(
            f"- Role: {t.get('role', '?')}, Task: {t.get('description', '?')}, "
            f"Success: {t.get('success', '?')}"
            for t in recent_tasks[:20]
        )
        prompt = (
            "Analyze these recent swarm tasks for recurring patterns that could "
            "be saved as reusable skills.\n\n"
            f"Tasks:\n{task_summaries}\n\n"
            "For each pattern found, respond in this exact format (one per line):\n"
            "SKILL|name|description|prompt_template|keyword1,keyword2\n\n"
            "Output ONLY SKILL lines or 'NONE' if no patterns found."
        )
        try:
            if asyncio.iscoroutinefunction(message_handler):
                response = await message_handler(
                    prompt, user="skill_store", channel="system:patterns"
                )
            else:
                response = message_handler(
                    prompt, user="skill_store", channel="system:patterns"
                )
            return self._parse_pattern_response(str(response))
        except Exception as e:
            logger.error(f"Pattern detection failed: {e}")
            return []

    def _parse_pattern_response(self, response: str) -> list[dict]:
        results = []
        for line in response.strip().split("\n"):
            line = line.strip()
            if not line.startswith("SKILL|"):
                continue
            parts = line.split("|")
            if len(parts) < 5:
                continue
            results.append({
                "name": parts[1].strip(),
                "description": parts[2].strip(),
                "prompt_template": parts[3].strip(),
                "trigger_keywords": [k.strip() for k in parts[4].split(",")],
            })
        return results

    def export_skills(self) -> dict:
        result = {}
        for name, skill in self._skills.items():
            result[name] = {
                "description": skill.description,
                "prompt_template": skill.prompt_template,
                "steps": skill.steps,
                "trigger_keywords": skill.trigger_keywords,
                "usage_count": skill.usage_count,
                "success_count": skill.success_count,
                "source": skill.source,
                "created_at": skill.created_at.isoformat(),
                "updated_at": skill.updated_at.isoformat(),
            }
        return result

    def import_skills(self, data: dict) -> None:
        self._skills.clear()
        for name, d in data.items():
            created_at = d.get("created_at")
            updated_at = d.get("updated_at")
            self._skills[name] = Skill(
                name=name,
                description=d.get("description", ""),
                prompt_template=d.get("prompt_template", ""),
                steps=d.get("steps", []),
                trigger_keywords=d.get("trigger_keywords", []),
                usage_count=d.get("usage_count", 0),
                success_count=d.get("success_count", 0),
                source=d.get("source", "manual"),
                created_at=datetime.fromisoformat(created_at) if created_at else datetime.now(timezone.utc),
                updated_at=datetime.fromisoformat(updated_at) if updated_at else datetime.now(timezone.utc),
            )

    async def flush_to_db(self) -> None:
        if self._db:
            try:
                await self._db.set_setting("skill_store", self.export_skills())
            except Exception as e:
                logger.error(f"Failed to flush skills: {e}")

    async def load_from_db(self) -> None:
        if self._db:
            try:
                data = await self._db.get_setting("skill_store")
                if data:
                    self.import_skills(data)
            except Exception as e:
                logger.error(f"Failed to load skills: {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_skill_store.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/core/skill_store.py tests/test_skill_store.py
git commit -m "feat: add SkillStore for reusable workflow/prompt management"
```

---

## Chunk 3: ToolGapDetector

### Task 4: ToolGapDetector 구현

**Files:**
- Create: `src/breadmind/core/tool_gap.py`
- Create: `tests/test_tool_gap.py`

- [ ] **Step 1: Write failing tests for ToolGapDetector**

```python
# tests/test_tool_gap.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.core.tool_gap import ToolGapDetector, ToolGapResult, MCPSuggestion


class TestToolGapResult:
    def test_unresolved_result(self):
        result = ToolGapResult(resolved=False, message="Not found", suggestions=[])
        assert result.resolved is False
        assert result.suggestions == []


class TestMCPSuggestion:
    def test_create_suggestion(self):
        s = MCPSuggestion(
            id="abc123",
            tool_name="kubectl_exec",
            mcp_name="kubernetes-mcp",
            mcp_description="K8s management tools",
            install_command="npx kubernetes-mcp",
            source="clawhub",
        )
        assert s.status == "pending"


class TestToolGapDetector:
    def _make_detector(self, search_results=None):
        registry = MagicMock()
        registry.get_tool.return_value = None

        mcp_manager = AsyncMock()
        search_engine = AsyncMock()
        if search_results is not None:
            search_engine.search = AsyncMock(return_value=search_results)
        else:
            search_engine.search = AsyncMock(return_value=[])

        return ToolGapDetector(
            tool_registry=registry,
            mcp_manager=mcp_manager,
            search_engine=search_engine,
        )

    @pytest.mark.asyncio
    async def test_check_no_suggestions(self):
        detector = self._make_detector(search_results=[])
        result = await detector.check_and_resolve("unknown_tool", {}, "user1", "ch1")
        assert result.resolved is False
        assert len(result.suggestions) == 0

    @pytest.mark.asyncio
    async def test_check_with_suggestions(self):
        mock_result = MagicMock()
        mock_result.name = "k8s-mcp"
        mock_result.description = "Kubernetes tools"
        mock_result.install_command = "npx k8s-mcp"
        mock_result.source = "clawhub"

        detector = self._make_detector(search_results=[mock_result])
        result = await detector.check_and_resolve("kubectl_exec", {}, "user1", "ch1")
        assert result.resolved is False  # Not yet installed
        assert len(result.suggestions) == 1
        assert result.suggestions[0].mcp_name == "k8s-mcp"

    @pytest.mark.asyncio
    async def test_cache_prevents_duplicate_searches(self):
        mock_result = MagicMock()
        mock_result.name = "mcp-a"
        mock_result.description = "desc"
        mock_result.install_command = "cmd"
        mock_result.source = "clawhub"

        detector = self._make_detector(search_results=[mock_result])
        await detector.check_and_resolve("tool_x", {}, "u", "c")
        await detector.check_and_resolve("tool_x", {}, "u", "c")
        # search should only be called once due to cache
        assert detector._search_engine.search.call_count == 1

    @pytest.mark.asyncio
    async def test_pending_installs(self):
        mock_result = MagicMock()
        mock_result.name = "mcp-b"
        mock_result.description = "desc"
        mock_result.install_command = "cmd"
        mock_result.source = "clawhub"

        detector = self._make_detector(search_results=[mock_result])
        await detector.check_and_resolve("tool_y", {}, "u", "c")
        pending = detector.get_pending_installs()
        assert len(pending) == 1
        assert pending[0]["mcp_name"] == "mcp-b"

    @pytest.mark.asyncio
    async def test_deny_install(self):
        mock_result = MagicMock()
        mock_result.name = "mcp-c"
        mock_result.description = "desc"
        mock_result.install_command = "cmd"
        mock_result.source = "clawhub"

        detector = self._make_detector(search_results=[mock_result])
        await detector.check_and_resolve("tool_z", {}, "u", "c")
        pending = detector.get_pending_installs()
        sid = pending[0]["id"]
        await detector.deny_install(sid)
        assert len(detector.get_pending_installs()) == 0

    @pytest.mark.asyncio
    async def test_search_failure_returns_empty(self):
        detector = self._make_detector()
        detector._search_engine.search = AsyncMock(side_effect=Exception("Network error"))
        result = await detector.check_and_resolve("tool_err", {}, "u", "c")
        assert result.resolved is False
        assert "failed" in result.message.lower() or len(result.suggestions) == 0

    @pytest.mark.asyncio
    async def test_approve_install(self):
        mock_result = MagicMock()
        mock_result.name = "mcp-d"
        mock_result.description = "desc"
        mock_result.install_command = "npx mcp-d"
        mock_result.source = "clawhub"

        detector = self._make_detector(search_results=[mock_result])
        await detector.check_and_resolve("tool_d", {}, "u", "c")
        pending = detector.get_pending_installs()
        sid = pending[0]["id"]

        # Mock successful install
        detector._mcp_manager.start_stdio_server = AsyncMock(return_value=[
            MagicMock(name="tool_d_v1"),
        ])
        result = await detector.approve_install(sid)
        assert "Installed" in result
        assert "mcp-d" in result

    @pytest.mark.asyncio
    async def test_approve_install_failure(self):
        mock_result = MagicMock()
        mock_result.name = "mcp-e"
        mock_result.description = "desc"
        mock_result.install_command = "npx mcp-e"
        mock_result.source = "clawhub"

        detector = self._make_detector(search_results=[mock_result])
        await detector.check_and_resolve("tool_e", {}, "u", "c")
        pending = detector.get_pending_installs()
        sid = pending[0]["id"]

        detector._mcp_manager.start_stdio_server = AsyncMock(side_effect=Exception("Server crash"))
        result = await detector.approve_install(sid)
        assert "failed" in result.lower()

    @pytest.mark.asyncio
    async def test_search_for_capability(self):
        mock_result = MagicMock()
        mock_result.name = "monitoring-mcp"
        mock_result.description = "Monitoring tools"
        mock_result.install_command = "npx monitoring-mcp"
        mock_result.source = "clawhub"

        detector = self._make_detector(search_results=[mock_result])
        detector._search_engine.search = AsyncMock(return_value=[mock_result])
        suggestions = await detector.search_for_capability("monitoring dashboards")
        assert len(suggestions) == 1
        assert suggestions[0].mcp_name == "monitoring-mcp"

    @pytest.mark.asyncio
    async def test_max_pending_eviction(self):
        mock_result = MagicMock()
        mock_result.name = "mcp"
        mock_result.description = "desc"
        mock_result.install_command = "cmd"
        mock_result.source = "clawhub"

        detector = self._make_detector(search_results=[mock_result])
        for i in range(12):
            # Clear cache to force new searches
            detector._search_cache.clear()
            await detector.check_and_resolve(f"tool_{i}", {}, "u", "c")
        # Max 10 pending
        assert len(detector.get_pending_installs()) <= 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_tool_gap.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement ToolGapDetector**

Create `src/breadmind/core/tool_gap.py`:
```python
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from breadmind.tools.registry import ToolRegistry
    from breadmind.tools.mcp_client import MCPClientManager
    from breadmind.tools.registry_search import RegistrySearchEngine

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 600  # 10 minutes
_MAX_PENDING = 10


@dataclass
class MCPSuggestion:
    id: str
    tool_name: str
    mcp_name: str
    mcp_description: str
    install_command: str
    source: str
    status: str = "pending"


@dataclass
class ToolGapResult:
    resolved: bool
    message: str
    suggestions: list[MCPSuggestion] = field(default_factory=list)


class ToolGapDetector:
    """Detects missing tools and suggests MCP servers to fill the gap."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        mcp_manager: MCPClientManager,
        search_engine: RegistrySearchEngine,
    ):
        self._registry = tool_registry
        self._mcp_manager = mcp_manager
        self._search_engine = search_engine
        self._pending: dict[str, MCPSuggestion] = {}
        self._search_cache: dict[str, tuple[float, list[MCPSuggestion]]] = {}
        self._gap_history: list[dict] = []

    async def check_and_resolve(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        user: str,
        channel: str,
    ) -> ToolGapResult:
        # Check cache first
        cached = self._search_cache.get(tool_name)
        if cached:
            cache_time, cached_suggestions = cached
            if time.monotonic() - cache_time < _CACHE_TTL_SECONDS:
                return ToolGapResult(
                    resolved=False,
                    message=f"Tool '{tool_name}' not found. Previously suggested MCP servers available.",
                    suggestions=cached_suggestions,
                )

        # Track gap history
        self._gap_history.append({
            "tool_name": tool_name,
            "user": user,
            "channel": channel,
            "timestamp": time.monotonic(),
        })

        # Search registries
        try:
            results = await self._search_engine.search(tool_name, limit=3)
        except Exception as e:
            logger.error(f"Registry search failed for '{tool_name}': {e}")
            return ToolGapResult(
                resolved=False,
                message=f"Registry search failed: {e}",
                suggestions=[],
            )

        if not results:
            self._search_cache[tool_name] = (time.monotonic(), [])
            return ToolGapResult(
                resolved=False,
                message=f"Tool '{tool_name}' not found. No matching MCP servers in registries.",
                suggestions=[],
            )

        suggestions = []
        for r in results:
            suggestion = MCPSuggestion(
                id=str(uuid.uuid4())[:8],
                tool_name=tool_name,
                mcp_name=r.name,
                mcp_description=r.description,
                install_command=r.install_command or "",
                source=r.source,
            )
            suggestions.append(suggestion)
            self._add_pending(suggestion)

        self._search_cache[tool_name] = (time.monotonic(), suggestions)

        names = ", ".join(s.mcp_name for s in suggestions)
        return ToolGapResult(
            resolved=False,
            message=(
                f"Tool '{tool_name}' not found. "
                f"Found MCP servers that may provide it: {names}. "
                f"Approval required to install."
            ),
            suggestions=suggestions,
        )

    def _add_pending(self, suggestion: MCPSuggestion) -> None:
        # FIFO eviction if at capacity
        while len(self._pending) >= _MAX_PENDING:
            oldest_key = next(iter(self._pending))
            del self._pending[oldest_key]
        self._pending[suggestion.id] = suggestion

    async def search_for_capability(
        self, description: str
    ) -> list[MCPSuggestion]:
        try:
            results = await self._search_engine.search(description, limit=5)
        except Exception as e:
            logger.error(f"Capability search failed: {e}")
            return []

        suggestions = []
        for r in results:
            suggestions.append(MCPSuggestion(
                id=str(uuid.uuid4())[:8],
                tool_name="",
                mcp_name=r.name,
                mcp_description=r.description,
                install_command=r.install_command or "",
                source=r.source,
            ))
        return suggestions

    def get_pending_installs(self) -> list[dict]:
        return [
            {
                "id": s.id,
                "tool_name": s.tool_name,
                "mcp_name": s.mcp_name,
                "mcp_description": s.mcp_description,
                "install_command": s.install_command,
                "source": s.source,
                "status": s.status,
            }
            for s in self._pending.values()
            if s.status == "pending"
        ]

    async def approve_install(self, suggestion_id: str) -> str:
        suggestion = self._pending.get(suggestion_id)
        if not suggestion or suggestion.status != "pending":
            return f"No pending suggestion found: {suggestion_id}"

        suggestion.status = "installing"
        try:
            definitions = await self._mcp_manager.start_stdio_server(
                name=suggestion.mcp_name,
                command=suggestion.install_command.split()[0] if suggestion.install_command else "npx",
                args=suggestion.install_command.split()[1:] if suggestion.install_command else [],
                source=suggestion.source,
            )
            suggestion.status = "installed"
            tool_names = [d.name for d in definitions] if definitions else []
            return (
                f"Installed '{suggestion.mcp_name}'. "
                f"Available tools: {', '.join(tool_names) if tool_names else 'none'}"
            )
        except Exception as e:
            suggestion.status = "failed"
            logger.error(f"MCP install failed for {suggestion.mcp_name}: {e}")
            return f"Install failed: {e}"

    async def deny_install(self, suggestion_id: str) -> None:
        suggestion = self._pending.get(suggestion_id)
        if suggestion:
            suggestion.status = "denied"
            del self._pending[suggestion_id]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_tool_gap.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/core/tool_gap.py tests/test_tool_gap.py
git commit -m "feat: add ToolGapDetector for automatic MCP server discovery on tool miss"
```

---

## Chunk 4: TeamBuilder + SwarmMember.source

### Task 5: SwarmMember.source 필드 및 SwarmCoordinator 수정

**Files:**
- Modify: `src/breadmind/core/swarm.py:31-34` (SwarmMember dataclass)
- Modify: `src/breadmind/core/swarm.py:162-232` (decompose + _parse_tasks)
- Modify: `src/breadmind/core/swarm.py:477-481` (add_role)
- Modify: `src/breadmind/core/swarm.py:499-514` (export/import_roles)
- Test: `tests/test_swarm.py`

- [ ] **Step 1: Write failing tests for SwarmMember.source and available_roles**

```python
# tests/test_swarm.py — 기존 파일에 아래 테스트 추가

class TestSwarmMemberSource:
    def test_default_source_is_manual(self):
        member = SwarmMember(role="test", system_prompt="prompt")
        assert member.source == "manual"

    def test_auto_source(self):
        member = SwarmMember(role="test", system_prompt="prompt", source="auto")
        assert member.source == "auto"


class TestSwarmCoordinatorAvailableRoles:
    @pytest.mark.asyncio
    async def test_decompose_uses_available_roles(self):
        responses = ["TASK|custom_role|Do the custom thing|none"]
        call_count = 0
        async def mock_handler(msg, user="", channel=""):
            nonlocal call_count
            call_count += 1
            return responses[0]
        coordinator = SwarmCoordinator(message_handler=mock_handler)
        available = {"custom_role", "general"}
        tasks = await coordinator.decompose("test goal", available_roles=available)
        # custom_role should be accepted (not replaced with general)
        assert any(t.role == "custom_role" for t in tasks)

    @pytest.mark.asyncio
    async def test_parse_tasks_respects_available_roles(self):
        coordinator = SwarmCoordinator()
        response = "TASK|auto_created|Do something|none\nTASK|unknown_xyz|Another|none"
        tasks = coordinator._parse_tasks(response, available_roles={"auto_created", "general"})
        assert tasks[0].role == "auto_created"
        assert tasks[1].role == "general"  # unknown_xyz → fallback


class TestSwarmManagerAddRoleSource:
    def test_add_role_with_source(self):
        manager = SwarmManager()
        manager.add_role("new_role", "prompt", "desc", source="auto")
        roles = manager.export_roles()
        assert roles["new_role"]["source"] == "auto"

    def test_import_roles_default_source(self):
        manager = SwarmManager()
        # Old format without source field
        manager.import_roles({"old_role": {"system_prompt": "p", "description": "d"}})
        member = manager._roles.get("old_role")
        assert member is not None
        assert member.source == "manual"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_swarm.py::TestSwarmMemberSource tests/test_swarm.py::TestSwarmCoordinatorAvailableRoles tests/test_swarm.py::TestSwarmManagerAddRoleSource -v`
Expected: FAIL

- [ ] **Step 3: Apply changes to swarm.py**

**SwarmMember** — add `source` field:
```python
@dataclass
class SwarmMember:
    role: str
    system_prompt: str
    description: str = ""
    source: str = "manual"
```

**SwarmCoordinator.decompose()** — add `available_roles` parameter. Change the decompose_prompt to use `available_roles` instead of `DEFAULT_ROLES.keys()`, and pass `available_roles` to `_parse_tasks()`.

**SwarmCoordinator._parse_tasks()** — add `available_roles: set[str] | None = None` parameter. Change the validation check from `if role not in DEFAULT_ROLES:` to `if available_roles and role not in available_roles:`.

**SwarmManager.add_role()** — add `source` parameter:
```python
def add_role(self, name: str, system_prompt: str, description: str = "", source: str = "manual"):
    self._roles[name] = SwarmMember(
        role=name, system_prompt=system_prompt,
        description=description or f"Custom role: {name}",
        source=source,
    )
```

**SwarmManager.export_roles()** — include source:
```python
def export_roles(self) -> dict[str, dict]:
    return {
        name: {"system_prompt": m.system_prompt, "description": m.description, "source": m.source}
        for name, m in self._roles.items()
    }
```

**SwarmManager.import_roles()** — handle missing source:
```python
def import_roles(self, roles_data: dict[str, dict]):
    self._roles.clear()
    for name, data in roles_data.items():
        self._roles[name] = SwarmMember(
            role=name,
            system_prompt=data.get("system_prompt", ""),
            description=data.get("description", f"Role: {name}"),
            source=data.get("source", "manual"),
        )
```

**SwarmManager._execute_swarm()** — pass roles to decompose:
```python
# In _execute_swarm, change line 336 from:
tasks = await self._coordinator.decompose(swarm.goal)
# to:
available_roles = set(self._roles.keys())
tasks = await self._coordinator.decompose(swarm.goal, available_roles=available_roles)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_swarm.py -v`
Expected: All PASS (including existing tests)

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/core/swarm.py tests/test_swarm.py
git commit -m "feat: add source field to SwarmMember, pass available_roles to decompose"
```

---

### Task 6: TeamBuilder 구현

**Files:**
- Create: `src/breadmind/core/team_builder.py`
- Create: `tests/test_team_builder.py`

- [ ] **Step 1: Write failing tests for TeamBuilder**

```python
# tests/test_team_builder.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from breadmind.core.team_builder import TeamBuilder, TeamPlan, RoleAssessment
from breadmind.core.swarm import SwarmManager, SwarmMember
from breadmind.core.performance import PerformanceTracker
from breadmind.core.skill_store import SkillStore


class TestRoleAssessment:
    def test_create(self):
        a = RoleAssessment(role="k8s_expert", relevance_score=0.9, success_rate=0.85, recommendation="use")
        assert a.recommendation == "use"


class TestTeamPlan:
    def test_create(self):
        plan = TeamPlan(
            goal="Check cluster health",
            selected_roles=["k8s_expert"],
            created_roles=[],
            skill_injections={},
            reasoning="K8s expert is relevant",
        )
        assert len(plan.selected_roles) == 1


class TestTeamBuilder:
    def _make_builder(self, llm_response=""):
        async def mock_handler(msg, user="", channel=""):
            return llm_response

        manager = SwarmManager()
        tracker = PerformanceTracker()
        skill_store = SkillStore()

        return TeamBuilder(
            swarm_manager=manager,
            tracker=tracker,
            skill_store=skill_store,
            message_handler=mock_handler,
        )

    @pytest.mark.asyncio
    async def test_build_team_selects_existing_roles(self):
        llm_response = (
            "ASSESS|k8s_expert|0.9|use\n"
            "ASSESS|proxmox_expert|0.2|skip\n"
            "ASSESS|general|0.5|use\n"
            "CREATE_NONE"
        )
        builder = self._make_builder(llm_response)
        plan = await builder.build_team("Check Kubernetes pod health")
        assert "k8s_expert" in plan.selected_roles
        assert "proxmox_expert" not in plan.selected_roles

    @pytest.mark.asyncio
    async def test_build_team_creates_new_role(self):
        llm_response = (
            "ASSESS|k8s_expert|0.3|skip\n"
            "ASSESS|general|0.4|skip\n"
            "CREATE|database_expert|Database and SQL optimization specialist|"
            "You are a database expert. Analyze query performance, index usage, and connection pools.|database,sql,query"
        )
        builder = self._make_builder(llm_response)
        plan = await builder.build_team("Optimize database performance")
        assert "database_expert" in plan.created_roles
        # Verify role was added to swarm manager
        roles = builder._swarm_manager.get_available_roles()
        role_names = [r["role"] for r in roles]
        assert "database_expert" in role_names

    @pytest.mark.asyncio
    async def test_max_3_created_roles(self):
        llm_response = (
            "ASSESS|general|0.1|skip\n"
            "CREATE|role1|d1|p1|k1\n"
            "CREATE|role2|d2|p2|k2\n"
            "CREATE|role3|d3|p3|k3\n"
            "CREATE|role4|d4|p4|k4\n"
        )
        builder = self._make_builder(llm_response)
        plan = await builder.build_team("Complex multi-domain task")
        assert len(plan.created_roles) <= 3

    @pytest.mark.asyncio
    async def test_cooldown_returns_cached_plan(self):
        llm_response = "ASSESS|k8s_expert|0.9|use\nCREATE_NONE"
        builder = self._make_builder(llm_response)
        plan1 = await builder.build_team("Check pods")
        plan2 = await builder.build_team("Check pods")
        # Same goal should return cached plan (cooldown)
        assert plan1.selected_roles == plan2.selected_roles

    @pytest.mark.asyncio
    async def test_skill_injections(self):
        llm_response = "ASSESS|k8s_expert|0.9|use\nCREATE_NONE"
        builder = self._make_builder(llm_response)
        # Add a matching skill
        await builder._skill_store.add_skill(
            "pod_check", "Check pod health", "List all pods and check status",
            ["list pods", "check status"], ["pod", "health", "check"], "manual",
        )
        plan = await builder.build_team("Check pod health")
        # Should inject matching skills
        assert isinstance(plan.skill_injections, dict)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_team_builder.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement TeamBuilder**

Create `src/breadmind/core/team_builder.py`:
```python
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from breadmind.core.swarm import SwarmManager, SwarmMember
    from breadmind.core.performance import PerformanceTracker
    from breadmind.core.skill_store import SkillStore

logger = logging.getLogger(__name__)

_COOLDOWN_SECONDS = 300  # 5 minutes
_MAX_NEW_ROLES = 3


@dataclass
class RoleAssessment:
    role: str
    relevance_score: float
    success_rate: float
    recommendation: str  # "use" | "skip" | "improve"


@dataclass
class TeamPlan:
    goal: str
    selected_roles: list[str] = field(default_factory=list)
    created_roles: list[str] = field(default_factory=list)
    skill_injections: dict[str, list[str]] = field(default_factory=dict)
    reasoning: str = ""


class TeamBuilder:
    """Builds optimal agent teams by analyzing goals and available roles."""

    def __init__(
        self,
        swarm_manager: SwarmManager,
        tracker: PerformanceTracker,
        skill_store: SkillStore,
        message_handler=None,
    ):
        self._swarm_manager = swarm_manager
        self._tracker = tracker
        self._skill_store = skill_store
        self._message_handler = message_handler
        self._plan_cache: dict[str, tuple[float, TeamPlan]] = {}

    async def build_team(self, goal: str) -> TeamPlan:
        # Check cooldown cache
        cache_key = goal.strip().lower()
        cached = self._plan_cache.get(cache_key)
        if cached:
            cache_time, cached_plan = cached
            if time.monotonic() - cache_time < _COOLDOWN_SECONDS:
                return cached_plan

        # Build role summary for LLM
        roles_info = self._build_roles_summary()
        prompt = self._build_analysis_prompt(goal, roles_info)

        # Get LLM analysis
        response = ""
        if self._message_handler:
            try:
                if asyncio.iscoroutinefunction(self._message_handler):
                    response = await self._message_handler(
                        prompt, user="team_builder", channel="system:team_build"
                    )
                else:
                    response = self._message_handler(
                        prompt, user="team_builder", channel="system:team_build"
                    )
            except Exception as e:
                logger.error(f"TeamBuilder LLM call failed: {e}")

        plan = self._parse_response(goal, str(response))

        # Register newly created roles
        for role_name in plan.created_roles:
            # Already added during parsing
            pass

        # Inject matching skills
        plan.skill_injections = await self._find_skill_injections(
            goal, plan.selected_roles + plan.created_roles
        )

        # Cache the plan
        self._plan_cache[cache_key] = (time.monotonic(), plan)

        return plan

    def _build_roles_summary(self) -> str:
        lines = []
        available_roles = self._swarm_manager.get_available_roles()
        for role_info in available_roles:
            name = role_info["role"]
            desc = role_info["description"]
            stats = self._tracker.get_role_stats(name)
            if stats and stats.total_runs > 0:
                lines.append(
                    f"- {name}: {desc} "
                    f"(runs={stats.total_runs}, success={stats.success_rate:.0%}, "
                    f"avg_time={stats.avg_duration_ms:.0f}ms)"
                )
            else:
                lines.append(f"- {name}: {desc} (no stats)")
        return "\n".join(lines)

    def _build_analysis_prompt(self, goal: str, roles_info: str) -> str:
        return (
            f"Analyze this goal and determine the optimal team composition.\n\n"
            f"Goal: {goal}\n\n"
            f"Available roles (with performance stats):\n{roles_info}\n\n"
            f"Instructions:\n"
            f"1. Assess each existing role's relevance (0.0-1.0) to the goal.\n"
            f"2. If no existing role fits a needed capability, create a new one (max {_MAX_NEW_ROLES}).\n\n"
            f"Respond in this exact format:\n"
            f"ASSESS|<role_name>|<relevance_0_to_1>|<use_or_skip>\n"
            f"CREATE|<new_role_name>|<description>|<system_prompt>|<keywords_comma_sep>\n"
            f"or CREATE_NONE if no new roles needed.\n\n"
            f"Output ONLY ASSESS and CREATE lines."
        )

    def _parse_response(self, goal: str, response: str) -> TeamPlan:
        selected: list[str] = []
        created: list[str] = []
        reasoning_parts: list[str] = []
        create_count = 0

        for line in response.strip().split("\n"):
            line = line.strip()

            if line.startswith("ASSESS|"):
                parts = line.split("|")
                if len(parts) >= 4:
                    role = parts[1].strip()
                    try:
                        score = float(parts[2].strip())
                    except ValueError:
                        score = 0.0
                    action = parts[3].strip().lower()
                    if action == "use" and score > 0.3:
                        selected.append(role)
                        reasoning_parts.append(f"{role}: relevance={score:.1f}")

            elif line.startswith("CREATE|") and create_count < _MAX_NEW_ROLES:
                parts = line.split("|")
                if len(parts) >= 4:
                    name = parts[1].strip()
                    desc = parts[2].strip()
                    sys_prompt = parts[3].strip()

                    # Avoid duplicates with existing roles
                    existing_names = {
                        r["role"] for r in self._swarm_manager.get_available_roles()
                    }
                    if name not in existing_names:
                        self._swarm_manager.add_role(
                            name, sys_prompt, desc, source="auto"
                        )
                        created.append(name)
                        selected.append(name)
                        create_count += 1
                        reasoning_parts.append(f"Created {name}: {desc}")

        # Fallback: if nothing selected, use general
        if not selected:
            selected = ["general"]
            reasoning_parts.append("Fallback to general role")

        return TeamPlan(
            goal=goal,
            selected_roles=selected,
            created_roles=created,
            reasoning="; ".join(reasoning_parts),
        )

    async def _find_skill_injections(
        self, goal: str, roles: list[str]
    ) -> dict[str, list[str]]:
        injections: dict[str, list[str]] = {}
        matching_skills = await self._skill_store.find_matching_skills(goal, limit=5)
        if matching_skills:
            # Distribute relevant skills to all selected roles
            skill_prompts = [s.prompt_template for s in matching_skills]
            for role in roles:
                injections[role] = skill_prompts
        return injections
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_team_builder.py -v`
Expected: All PASS

- [ ] **Step 5: Run all swarm-related tests**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_swarm.py tests/test_team_builder.py tests/test_performance.py tests/test_skill_store.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/breadmind/core/team_builder.py tests/test_team_builder.py
git commit -m "feat: add TeamBuilder for automatic team composition with role gap analysis"
```

---

## Chunk 5: Integration (CoreAgent + SwarmManager + Meta Tools + main.py)

### Task 7: CoreAgent에 ToolGapDetector 연결

**Files:**
- Modify: `src/breadmind/core/agent.py:21-46` (constructor)
- Modify: `src/breadmind/core/agent.py:293-309` (_execute_one)
- Test: `tests/test_agent.py`

- [ ] **Step 1: Write failing test for CoreAgent tool gap integration**

```python
# tests/test_agent.py — 기존 파일에 추가
@pytest.mark.asyncio
async def test_agent_triggers_tool_gap_detector_on_not_found():
    """CoreAgent should call ToolGapDetector when a tool returns not_found=True."""
    from unittest.mock import AsyncMock, MagicMock
    from breadmind.core.agent import CoreAgent
    from breadmind.tools.registry import ToolRegistry, ToolResult
    from breadmind.core.safety import SafetyGuard

    registry = MagicMock(spec=ToolRegistry)
    registry.get_all_definitions.return_value = [
        MagicMock(name="some_tool", description="test", parameters={})
    ]
    registry.execute = AsyncMock(return_value=ToolResult(
        success=False, output="Tool not found: missing_tool", not_found=True
    ))

    provider = AsyncMock()
    # First response: LLM calls a tool, second response: LLM gives text answer
    from breadmind.llm.base import LLMResponse, ToolCall, Usage
    provider.chat = AsyncMock(side_effect=[
        LLMResponse(
            content="", has_tool_calls=True,
            tool_calls=[ToolCall(id="tc1", name="missing_tool", arguments={})],
            usage=Usage(input_tokens=10, output_tokens=10),
        ),
        LLMResponse(
            content="I couldn't find that tool.", has_tool_calls=False,
            tool_calls=[], usage=Usage(input_tokens=10, output_tokens=10),
        ),
    ])

    guard = MagicMock(spec=SafetyGuard)
    guard.check.return_value = MagicMock(value="allow")
    guard.check.return_value = __import__('breadmind.core.safety', fromlist=['SafetyResult']).SafetyResult.ALLOW
    guard.check_cooldown.return_value = True

    gap_detector = AsyncMock()
    gap_detector.check_and_resolve = AsyncMock(return_value=MagicMock(
        resolved=False,
        message="Tool 'missing_tool' not found. Found MCP: k8s-mcp.",
        suggestions=[],
    ))

    agent = CoreAgent(
        provider=provider, tool_registry=registry,
        safety_guard=guard, tool_gap_detector=gap_detector,
    )
    await agent.handle_message("do something", "user", "ch")
    gap_detector.check_and_resolve.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_agent.py::test_agent_triggers_tool_gap_detector_on_not_found -v`
Expected: FAIL — `TypeError: CoreAgent.__init__() got an unexpected keyword argument 'tool_gap_detector'`

- [ ] **Step 3: Modify CoreAgent**

In `src/breadmind/core/agent.py`:

Add to imports:
```python
if TYPE_CHECKING:
    from breadmind.memory.working import WorkingMemory
    from breadmind.core.tool_gap import ToolGapDetector
```

Add `tool_gap_detector` parameter to `__init__()`:
```python
def __init__(
    self,
    ...
    tool_gap_detector: ToolGapDetector | None = None,
):
    ...
    self._tool_gap_detector = tool_gap_detector
```

Modify `_execute_one()` inner function (around line 293-309). After getting `result` from `self._tools.execute()`, add:
```python
async def _execute_one(tc: ToolCall) -> tuple[ToolCall, str, float]:
    t_start = time.monotonic()
    try:
        result = await asyncio.wait_for(
            self._tools.execute(tc.name, tc.arguments),
            timeout=self._tool_timeout,
        )
        # Check for tool gap
        if result.not_found and self._tool_gap_detector:
            try:
                gap_result = await self._tool_gap_detector.check_and_resolve(
                    tc.name, tc.arguments, user, channel,
                )
                elapsed = (time.monotonic() - t_start) * 1000
                return tc, f"[success=False] {gap_result.message}", elapsed
            except Exception as e:
                logger.error(f"ToolGapDetector error: {e}")
        elapsed = (time.monotonic() - t_start) * 1000
        prefix = f"[success={result.success}]"
        return tc, f"{prefix} {result.output}", elapsed
    except asyncio.TimeoutError:
        ...  # unchanged
    except Exception as e:
        ...  # unchanged
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_agent.py::test_agent_triggers_tool_gap_detector_on_not_found -v`
Expected: PASS

- [ ] **Step 5: Run all agent tests to verify no regression**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_agent.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/breadmind/core/agent.py tests/test_agent.py
git commit -m "feat: integrate ToolGapDetector into CoreAgent tool execution loop"
```

---

### Task 8: SwarmManager에 TeamBuilder + PerformanceTracker 연결

**Files:**
- Modify: `src/breadmind/core/swarm.py:279-293` (SwarmManager.__init__)
- Modify: `src/breadmind/core/swarm.py:331-433` (_execute_swarm)
- Test: `tests/test_swarm.py`

- [ ] **Step 1: Write failing tests for SwarmManager integration**

```python
# tests/test_swarm.py — 기존 파일에 추가

class TestSwarmManagerIntegration:
    @pytest.mark.asyncio
    async def test_swarm_records_performance(self):
        """SwarmManager should record task results to PerformanceTracker."""
        from breadmind.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        call_idx = 0
        async def mock_handler(msg, user="", channel=""):
            nonlocal call_idx
            call_idx += 1
            if "decompose" in channel or "Decompose" in msg:
                return "TASK|general|Do something|none"
            if "aggregate" in channel or "aggregating" in msg.lower():
                return "Summary: all good"
            return "Task completed successfully"

        manager = SwarmManager(message_handler=mock_handler, tracker=tracker)
        swarm = await manager.spawn_swarm("Test goal")
        # Wait for completion
        for _ in range(50):
            await asyncio.sleep(0.1)
            info = manager.get_swarm(swarm.id)
            if info and info["status"] in ("completed", "failed"):
                break
        stats = tracker.get_role_stats("general")
        assert stats is not None
        assert stats.total_runs >= 1

    @pytest.mark.asyncio
    async def test_swarm_uses_team_builder(self):
        """SwarmManager should call TeamBuilder before decompose."""
        from breadmind.core.performance import PerformanceTracker
        from breadmind.core.skill_store import SkillStore
        from breadmind.core.team_builder import TeamBuilder

        tracker = PerformanceTracker()
        skill_store = SkillStore()
        team_builder_called = False

        async def mock_handler(msg, user="", channel=""):
            if "team_build" in channel:
                nonlocal team_builder_called
                team_builder_called = True
                return "ASSESS|general|0.8|use\nCREATE_NONE"
            if "decompose" in channel:
                return "TASK|general|Do task|none"
            if "aggregate" in channel:
                return "Done"
            return "OK"

        manager = SwarmManager(message_handler=mock_handler, tracker=tracker)
        team_builder = TeamBuilder(manager, tracker, skill_store, mock_handler)
        manager.set_team_builder(team_builder)

        swarm = await manager.spawn_swarm("Test")
        for _ in range(50):
            await asyncio.sleep(0.1)
            info = manager.get_swarm(swarm.id)
            if info and info["status"] in ("completed", "failed"):
                break
        assert team_builder_called
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_swarm.py::TestSwarmManagerIntegration -v`
Expected: FAIL

- [ ] **Step 3: Modify SwarmManager**

In `src/breadmind/core/swarm.py`, modify `SwarmManager.__init__()`:
```python
def __init__(self, message_handler=None, custom_roles=None,
             tracker=None, team_builder=None):
    ...
    self._tracker = tracker
    self._team_builder = team_builder
    self._task_complete_count = 0
```

Add setter:
```python
def set_team_builder(self, team_builder):
    self._team_builder = team_builder

def set_tracker(self, tracker):
    self._tracker = tracker
```

In `_execute_swarm()`, before decompose (line 336), add TeamBuilder call:
```python
# Phase 0: Build optimal team
if self._team_builder:
    try:
        team_plan = await self._team_builder.build_team(swarm.goal)
        logger.info(f"TeamBuilder selected roles: {team_plan.selected_roles}, created: {team_plan.created_roles}")
    except Exception as e:
        logger.error(f"TeamBuilder failed, proceeding with defaults: {e}")
```

After each task completes in `run_task()` (around line 405), add PerformanceTracker recording:
```python
# After task.status = "completed" or "failed"
if self._tracker:
    elapsed = (time.monotonic() - t_start) * 1000 if 't_start' in dir() else 0
    await self._tracker.record_task_result(
        role=task.role,
        task_desc=task.description,
        success=(task.status == "completed"),
        duration_ms=elapsed,
        result_summary=task.result[:200] if task.result else task.error[:200],
    )
```

Note: add `t_start = time.monotonic()` at the beginning of `run_task()`.

Also add pattern detection trigger after performance recording:
```python
# After recording to tracker
if self._tracker:
    self._task_complete_count += 1
    if self._task_complete_count % 10 == 0 and self._skill_store:
        try:
            recent = [
                {"role": t.role, "description": t.description,
                 "success": t.status == "completed"}
                for t in tasks if t.status in ("completed", "failed")
            ]
            patterns = await self._skill_store.detect_patterns(
                recent, self._message_handler
            )
            if patterns:
                logger.info(f"Detected {len(patterns)} skill patterns from recent tasks")
        except Exception as e:
            logger.error(f"Pattern detection failed: {e}")
```

Add `_skill_store` field and setter to SwarmManager:
```python
def __init__(self, ..., skill_store=None):
    ...
    self._skill_store = skill_store

def set_skill_store(self, skill_store):
    self._skill_store = skill_store
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_swarm.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/core/swarm.py tests/test_swarm.py
git commit -m "feat: integrate TeamBuilder, PerformanceTracker, and pattern detection into SwarmManager"
```

---

### Task 9: Meta tools 추가 (skill_manage, performance_report)

**Files:**
- Modify: `src/breadmind/tools/meta.py`
- Test: `tests/test_meta_tools.py`

- [ ] **Step 1: Write failing tests for new meta tools**

```python
# tests/test_meta_tools.py — 기존 파일에 추가
@pytest.mark.asyncio
async def test_skill_manage_list():
    from breadmind.core.skill_store import SkillStore
    from breadmind.tools.meta import create_expansion_tools
    skill_store = SkillStore()
    await skill_store.add_skill("s1", "desc", "prompt", [], ["kw"], "manual")
    tools = create_expansion_tools(skill_store=skill_store, tracker=None)
    result = await tools["skill_manage"](action="list")
    assert "s1" in result

@pytest.mark.asyncio
async def test_skill_manage_add():
    from breadmind.core.skill_store import SkillStore
    from breadmind.tools.meta import create_expansion_tools
    skill_store = SkillStore()
    tools = create_expansion_tools(skill_store=skill_store, tracker=None)
    result = await tools["skill_manage"](
        action="add", name="new_skill",
        description="A new skill", prompt_template="Do things",
        trigger_keywords="kw1,kw2",
    )
    assert "new_skill" in result
    assert await skill_store.get_skill("new_skill") is not None

@pytest.mark.asyncio
async def test_performance_report():
    from breadmind.core.performance import PerformanceTracker
    from breadmind.tools.meta import create_expansion_tools
    tracker = PerformanceTracker()
    await tracker.record_task_result("role_a", "t1", True, 100.0, "ok")
    tools = create_expansion_tools(skill_store=None, tracker=tracker)
    result = await tools["performance_report"]()
    assert "role_a" in result

@pytest.mark.asyncio
async def test_performance_report_specific_role():
    from breadmind.core.performance import PerformanceTracker
    from breadmind.tools.meta import create_expansion_tools
    tracker = PerformanceTracker()
    await tracker.record_task_result("role_a", "t1", True, 100.0, "ok")
    tools = create_expansion_tools(skill_store=None, tracker=tracker)
    result = await tools["performance_report"](role="role_a")
    assert "role_a" in result
    assert "100" in result or "1" in result  # success rate or run count
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_meta_tools.py::test_skill_manage_list tests/test_meta_tools.py::test_performance_report -v`
Expected: FAIL

- [ ] **Step 3: Add create_expansion_tools() to meta.py**

Append to `src/breadmind/tools/meta.py`:
```python
def create_expansion_tools(
    skill_store=None,
    tracker=None,
) -> dict:

    @tool(description="Manage reusable skills. action: 'list', 'add', 'update', 'remove'. For add: provide name, description, prompt_template, trigger_keywords (comma-separated).")
    async def skill_manage(
        action: str, name: str = "", description: str = "",
        prompt_template: str = "", trigger_keywords: str = "",
    ) -> str:
        if skill_store is None:
            return "SkillStore not available."

        if action == "list":
            skills = await skill_store.list_skills()
            if not skills:
                return "No skills registered."
            lines = []
            for s in skills:
                lines.append(f"- **{s.name}** ({s.source}): {s.description}")
                lines.append(f"  Keywords: {', '.join(s.trigger_keywords)}")
                lines.append(f"  Usage: {s.usage_count} (success: {s.success_count})")
            return "\n".join(lines)

        if action == "add":
            if not name or not description:
                return "Error: name and description required."
            try:
                kws = [k.strip() for k in trigger_keywords.split(",") if k.strip()]
                skill = await skill_store.add_skill(
                    name, description, prompt_template, [], kws, "manual",
                )
                return f"Skill '{skill.name}' created."
            except ValueError as e:
                return f"Error: {e}"

        if action == "update":
            if not name:
                return "Error: name required."
            kwargs = {}
            if description:
                kwargs["description"] = description
            if prompt_template:
                kwargs["prompt_template"] = prompt_template
            if trigger_keywords:
                kwargs["trigger_keywords"] = [k.strip() for k in trigger_keywords.split(",")]
            try:
                await skill_store.update_skill(name, **kwargs)
                return f"Skill '{name}' updated."
            except ValueError as e:
                return f"Error: {e}"

        if action == "remove":
            if not name:
                return "Error: name required."
            removed = await skill_store.remove_skill(name)
            return f"Skill '{name}' removed." if removed else f"Skill '{name}' not found."

        return f"Unknown action: {action}. Use list, add, update, or remove."

    @tool(description="View performance stats for swarm roles. Optionally specify a role name for detailed stats.")
    async def performance_report(role: str = "") -> str:
        if tracker is None:
            return "PerformanceTracker not available."

        if role:
            stats = tracker.get_role_stats(role)
            if not stats:
                return f"No stats for role '{role}'."
            return (
                f"**{role}** — {stats.total_runs} runs, "
                f"{stats.success_rate:.0%} success rate, "
                f"avg {stats.avg_duration_ms:.0f}ms\n"
                f"Successes: {stats.successes}, Failures: {stats.failures}\n"
                f"Feedback entries: {len(stats.feedback_history)}"
            )

        all_stats = tracker.get_all_stats()
        if not all_stats:
            return "No performance data available."
        lines = []
        for name, stats in sorted(all_stats.items()):
            lines.append(
                f"- **{name}**: {stats.total_runs} runs, "
                f"{stats.success_rate:.0%} success, avg {stats.avg_duration_ms:.0f}ms"
            )
        return "\n".join(lines)

    return {
        "skill_manage": skill_manage,
        "performance_report": performance_report,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_meta_tools.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/tools/meta.py tests/test_meta_tools.py
git commit -m "feat: add skill_manage and performance_report meta tools"
```

---

### Task 10: main.py 통합 및 Web API 엔드포인트

**Files:**
- Modify: `src/breadmind/main.py` (initialization sequence)
- Modify: `src/breadmind/web/app.py` (new API routes)

- [ ] **Step 1: Update main.py initialization**

After existing component initialization (around line 170, after meta tools), add:
```python
# Self-expansion components
from breadmind.core.performance import PerformanceTracker
from breadmind.core.skill_store import SkillStore
from breadmind.core.tool_gap import ToolGapDetector
from breadmind.core.team_builder import TeamBuilder

performance_tracker = PerformanceTracker(db=db)
await performance_tracker.load_from_db()

skill_store = SkillStore(db=db, tracker=performance_tracker)
await skill_store.load_from_db()

tool_gap_detector = ToolGapDetector(
    tool_registry=registry,
    mcp_manager=mcp_manager,
    search_engine=search_engine,
)

# Register expansion meta tools
from breadmind.tools.meta import create_expansion_tools
expansion_tools = create_expansion_tools(
    skill_store=skill_store,
    tracker=performance_tracker,
)
for func in expansion_tools.values():
    registry.register(func)
```

Inject into CoreAgent (modify the CoreAgent construction):
```python
agent = CoreAgent(
    ...,
    tool_gap_detector=tool_gap_detector,
)
```

After SwarmManager initialization, add:
```python
swarm_manager.set_tracker(performance_tracker)
team_builder = TeamBuilder(swarm_manager, performance_tracker, skill_store, agent.handle_message)
swarm_manager.set_team_builder(team_builder)
```

Wire skill_store into SwarmManager:
```python
swarm_manager.set_skill_store(skill_store)
```

Add periodic flush task with auto-role cleanup:
```python
async def _flush_expansion_data():
    while True:
        await asyncio.sleep(300)  # 5 minutes
        await performance_tracker.flush_to_db()
        await skill_store.flush_to_db()
        # Auto-cleanup stale auto-created roles
        if swarm_manager and performance_tracker:
            from datetime import datetime, timezone, timedelta
            for role_info in swarm_manager.get_available_roles():
                name = role_info["role"]
                member = swarm_manager._roles.get(name)
                if not member or member.source != "auto":
                    continue
                stats = performance_tracker.get_role_stats(name)
                if stats and stats.total_runs > 0 and stats.success_rate < 0.2:
                    swarm_manager.remove_role(name)
                    logger.info(f"Auto-removed underperforming role '{name}' (success={stats.success_rate:.0%})")
                elif not stats or stats.total_runs == 0:
                    # Check if role was created > 30 days ago (tracked via export data)
                    pass  # Timestamp tracking for cleanup is deferred to v2

asyncio.create_task(_flush_expansion_data())
```

- [ ] **Step 2: Add Web API endpoints**

In `src/breadmind/web/app.py`, add skills and performance endpoints (after existing swarm routes):

```python
# Skills endpoints
@app.get("/api/skills")
async def list_skills():
    skills = await skill_store.list_skills()
    return [{"name": s.name, "description": s.description, "source": s.source,
             "usage_count": s.usage_count, "trigger_keywords": s.trigger_keywords} for s in skills]

@app.post("/api/skills")
async def create_skill(body: dict):
    skill = await skill_store.add_skill(
        name=body["name"], description=body["description"],
        prompt_template=body.get("prompt_template", ""),
        steps=body.get("steps", []),
        trigger_keywords=body.get("trigger_keywords", []),
        source="manual",
    )
    await skill_store.flush_to_db()
    return {"name": skill.name, "status": "created"}

@app.put("/api/skills/{name}")
async def update_skill(name: str, body: dict):
    await skill_store.update_skill(name, **body)
    await skill_store.flush_to_db()
    return {"name": name, "status": "updated"}

@app.delete("/api/skills/{name}")
async def delete_skill(name: str):
    removed = await skill_store.remove_skill(name)
    if removed:
        await skill_store.flush_to_db()
    return {"name": name, "removed": removed}

# Performance endpoints
@app.get("/api/performance")
async def get_performance():
    all_stats = performance_tracker.get_all_stats()
    return {name: {"total_runs": s.total_runs, "success_rate": s.success_rate,
                    "avg_duration_ms": s.avg_duration_ms, "failures": s.failures}
            for name, s in all_stats.items()}

@app.get("/api/performance/{role}")
async def get_role_performance(role: str):
    stats = performance_tracker.get_role_stats(role)
    if not stats:
        return {"error": f"No stats for '{role}'"}
    return {"role": role, "total_runs": stats.total_runs,
            "success_rate": stats.success_rate, "avg_duration_ms": stats.avg_duration_ms,
            "successes": stats.successes, "failures": stats.failures,
            "feedback_count": len(stats.feedback_history)}
```

- [ ] **Step 3: Verify imports resolve**

Run: `cd D:/Projects/breadmind && python -c "from breadmind.core.performance import PerformanceTracker; from breadmind.core.skill_store import SkillStore; from breadmind.core.tool_gap import ToolGapDetector; from breadmind.core.team_builder import TeamBuilder; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Run all tests**

Run: `cd D:/Projects/breadmind && python -m pytest tests/ -v --tb=short`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/main.py src/breadmind/web/app.py
git commit -m "feat: integrate self-expansion system into main.py and web API"
```

---

## Chunk 6: Final integration test

### Task 11: End-to-end 통합 테스트

**Files:**
- Create: `tests/test_self_expansion.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_self_expansion.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from breadmind.core.performance import PerformanceTracker
from breadmind.core.skill_store import SkillStore
from breadmind.core.tool_gap import ToolGapDetector
from breadmind.core.team_builder import TeamBuilder
from breadmind.core.swarm import SwarmManager
from breadmind.tools.registry import ToolRegistry


class TestSelfExpansionIntegration:
    @pytest.mark.asyncio
    async def test_full_expansion_flow(self):
        """Test: TeamBuilder creates role → Swarm executes → PerformanceTracker records → SkillStore detects pattern."""
        tracker = PerformanceTracker()
        skill_store = SkillStore(tracker=tracker)

        call_log = []
        async def mock_handler(msg, user="", channel=""):
            call_log.append(channel)
            if "team_build" in channel:
                return "ASSESS|general|0.3|skip\nCREATE|test_expert|Test expert|You are a test expert.|test"
            if "decompose" in channel:
                return "TASK|test_expert|Run the test analysis|none"
            if "aggregate" in channel:
                return "Test analysis complete"
            return "Task done"

        manager = SwarmManager(message_handler=mock_handler, tracker=tracker)
        team_builder = TeamBuilder(manager, tracker, skill_store, mock_handler)
        manager.set_team_builder(team_builder)

        swarm = await manager.spawn_swarm("Analyze test coverage")
        for _ in range(100):
            await asyncio.sleep(0.1)
            info = manager.get_swarm(swarm.id)
            if info and info["status"] in ("completed", "failed"):
                break

        # Verify: role was created
        roles = [r["role"] for r in manager.get_available_roles()]
        assert "test_expert" in roles

        # Verify: performance was tracked
        stats = tracker.get_role_stats("test_expert")
        assert stats is not None
        assert stats.total_runs >= 1

    @pytest.mark.asyncio
    async def test_tool_gap_to_suggestion_flow(self):
        """Test: unknown tool → ToolGapDetector suggests MCP → suggestion available."""
        registry = MagicMock(spec=ToolRegistry)
        mcp_manager = AsyncMock()
        search_engine = AsyncMock()

        mock_result = MagicMock()
        mock_result.name = "grafana-mcp"
        mock_result.description = "Grafana dashboard tools"
        mock_result.install_command = "npx grafana-mcp"
        mock_result.source = "clawhub"
        search_engine.search = AsyncMock(return_value=[mock_result])

        detector = ToolGapDetector(registry, mcp_manager, search_engine)
        result = await detector.check_and_resolve("grafana_query", {}, "user", "ch")

        assert not result.resolved
        assert len(result.suggestions) == 1
        assert result.suggestions[0].mcp_name == "grafana-mcp"

        # Verify pending install exists
        pending = detector.get_pending_installs()
        assert len(pending) == 1

    @pytest.mark.asyncio
    async def test_export_import_roundtrip(self):
        """Test: all components survive export/import cycle."""
        tracker = PerformanceTracker()
        await tracker.record_task_result("role_a", "task1", True, 100.0, "ok")
        exported_tracker = tracker.export_stats()

        skill_store = SkillStore()
        await skill_store.add_skill("s1", "desc", "prompt", ["step"], ["kw"], "auto")
        exported_skills = skill_store.export_skills()

        # Import into fresh instances
        tracker2 = PerformanceTracker()
        tracker2.import_stats(exported_tracker)
        assert tracker2.get_role_stats("role_a").total_runs == 1

        skill_store2 = SkillStore()
        skill_store2.import_skills(exported_skills)
        assert (await skill_store2.get_skill("s1")).source == "auto"
```

- [ ] **Step 2: Run integration tests**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_self_expansion.py -v`
Expected: All PASS

- [ ] **Step 3: Run full test suite**

Run: `cd D:/Projects/breadmind && python -m pytest tests/ -v --tb=short`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_self_expansion.py
git commit -m "test: add end-to-end integration tests for self-expansion system"
```

- [ ] **Step 5: Final commit — update spec status**

```bash
git add docs/
git commit -m "docs: add self-expansion design spec and implementation plan"
```
