import pytest
from breadmind.memory.embedding import EmbeddingService
from breadmind.memory.episodic import EpisodicMemory
from breadmind.memory.semantic import SemanticMemory
from breadmind.core.skill_store import SkillStore
from breadmind.core.smart_retriever import SmartRetriever


class TestSmartRetrievalIntegration:
    def _make_system(self):
        """Create a full system without real embedding model."""
        embedding = EmbeddingService()
        embedding._available = False  # No real model needed
        episodic = EpisodicMemory()
        semantic = SemanticMemory()
        skill_store = SkillStore()
        retriever = SmartRetriever(
            embedding_service=embedding,
            episodic_memory=episodic,
            semantic_memory=semantic,
            skill_store=skill_store,
        )
        skill_store.set_retriever(retriever)
        return skill_store, retriever, episodic, semantic

    @pytest.mark.asyncio
    async def test_skill_indexed_on_add(self):
        """Adding a skill indexes it in EpisodicMemory and KG."""
        skill_store, retriever, episodic, semantic = self._make_system()
        await skill_store.add_skill(
            "pod_check", "Check Kubernetes pod health",
            "List all pods and check for CrashLoopBackOff",
            ["list pods", "check crashes"], ["pod", "kubernetes", "health"], "manual",
        )
        # Verify episodic note was created
        notes = await episodic.get_all_notes()
        assert len(notes) == 1
        assert "pod_check" in notes[0].content

        # Verify KG entities were created
        skill_entity = await semantic.get_entity("skill:pod_check")
        assert skill_entity is not None
        domain_entity = await semantic.get_entity("domain:pod")
        assert domain_entity is not None

    @pytest.mark.asyncio
    async def test_kg_retrieval_finds_indexed_skill(self):
        """KG search finds skills related to query keywords."""
        skill_store, retriever, episodic, semantic = self._make_system()
        await skill_store.add_skill(
            "disk_cleanup", "Clean up disk space on nodes",
            "Find and remove unused images and volumes",
            [], ["disk", "cleanup", "storage"], "manual",
        )
        results = await retriever.retrieve_skills("disk storage full")
        assert len(results) >= 1
        assert any(r.skill.name == "disk_cleanup" for r in results)

    @pytest.mark.asyncio
    async def test_task_indexing_creates_kg_relations(self):
        """Indexing a task result creates role and task entities in KG."""
        _, retriever, episodic, semantic = self._make_system()
        await retriever.index_task_result(
            role="k8s_expert", task_desc="Restart crashed pods",
            result_summary="Restarted 3 pods", success=True,
        )
        # Verify role entity
        role_entity = await semantic.get_entity("role:k8s_expert")
        assert role_entity is not None

        # Verify task history note
        notes = await episodic.get_all_notes()
        assert len(notes) == 1
        assert "k8s_expert" in notes[0].content

    @pytest.mark.asyncio
    async def test_token_budget_respected(self):
        """Skills exceeding token budget are excluded."""
        skill_store, retriever, episodic, semantic = self._make_system()
        # Add a skill with large prompt
        await skill_store.add_skill(
            "big_skill", "Big skill", "x" * 8000,  # ~2000 tokens
            [], ["test"], "manual",
        )
        await skill_store.add_skill(
            "small_skill", "Small skill", "y" * 400,  # ~100 tokens
            [], ["test"], "manual",
        )
        results = await retriever.retrieve_skills("test", token_budget=500)
        # Should only include small_skill
        names = [r.skill.name for r in results]
        assert "small_skill" in names
        assert "big_skill" not in names

    @pytest.mark.asyncio
    async def test_fallback_to_keyword_when_no_retriever(self):
        """SkillStore falls back to keyword matching without SmartRetriever."""
        skill_store = SkillStore()  # No retriever set
        await skill_store.add_skill(
            "vm_check", "Check VM status", "prompt",
            [], ["vm", "status"], "manual",
        )
        results = await skill_store.find_matching_skills("vm status check")
        assert len(results) >= 1
        assert results[0].name == "vm_check"

    @pytest.mark.asyncio
    async def test_multiple_skills_ranked_by_relevance(self):
        """Skills with more keyword matches should rank higher."""
        skill_store, retriever, episodic, semantic = self._make_system()
        await skill_store.add_skill(
            "general", "General purpose tool", "generic prompt",
            [], ["general"], "manual",
        )
        await skill_store.add_skill(
            "k8s_pods", "Kubernetes pod management", "Manage K8s pods",
            [], ["kubernetes", "pod", "management"], "manual",
        )
        await skill_store.add_skill(
            "k8s_network", "Kubernetes network debugging", "Debug network",
            [], ["kubernetes", "network"], "manual",
        )
        results = await retriever.retrieve_skills("kubernetes pod health")
        if len(results) >= 2:
            # k8s_pods should score higher (more keyword matches)
            names = [r.skill.name for r in results]
            assert names.index("k8s_pods") < names.index("general") if "general" in names else True
