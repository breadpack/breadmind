import pytest
from breadmind.core.skill_store import SkillStore, Skill


class TestSkill:
    def test_create_skill(self):
        skill = Skill(name="pod_restart_check", description="Check and restart crashed pods",
            prompt_template="Check all pods in namespace {namespace} and restart crashed ones.",
            steps=["List pods", "Find CrashLoopBackOff", "Restart"],
            trigger_keywords=["pod", "restart", "crash"])
        assert skill.name == "pod_restart_check"
        assert skill.usage_count == 0
        assert skill.source == "manual"


class TestSkillStore:
    @pytest.mark.asyncio
    async def test_add_and_get_skill(self):
        store = SkillStore()
        skill = await store.add_skill(name="test_skill", description="A test skill",
            prompt_template="Do the test thing", steps=["step1"],
            trigger_keywords=["test"], source="manual")
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
        assert skill.prompt_template == "old prompt"

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
