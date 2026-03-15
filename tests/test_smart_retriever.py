import pytest
from unittest.mock import AsyncMock, MagicMock
from breadmind.core.smart_retriever import (
    SmartRetriever, ScoredSkill, ContextItem, extract_keywords,
)


class TestExtractKeywords:
    def test_basic(self):
        kws = extract_keywords("Check Kubernetes pod health status")
        assert "kubernetes" in kws
        assert "pod" in kws
        assert "health" in kws
        assert "status" in kws

    def test_filters_stopwords(self):
        kws = extract_keywords("the quick brown fox")
        assert "the" not in kws
        assert "quick" in kws

    def test_filters_short_words(self):
        kws = extract_keywords("a b cd ef")
        assert "a" not in kws
        assert "b" not in kws
        assert "cd" in kws

    def test_deduplicates(self):
        kws = extract_keywords("pod pod pod")
        assert kws.count("pod") == 1

    def test_empty(self):
        assert extract_keywords("") == []


class TestScoredSkill:
    def test_create(self):
        skill = MagicMock()
        ss = ScoredSkill(skill=skill, score=0.8, token_estimate=100, source="vector")
        assert ss.score == 0.8


class TestSmartRetriever:
    def _make_retriever(self, embedding_available=False):
        embedding = MagicMock()
        embedding.is_available.return_value = embedding_available
        embedding.encode = AsyncMock(
            return_value=[0.1] * 384 if embedding_available else None,
        )
        embedding.cosine_similarity = MagicMock(return_value=0.8)

        episodic = AsyncMock()
        episodic.add_note = AsyncMock(
            return_value=MagicMock(id=1, tags=[], embedding=None),
        )
        episodic.get_all_notes = AsyncMock(return_value=[])
        episodic.search_by_keywords = AsyncMock(return_value=[])

        semantic = AsyncMock()
        semantic.add_entity = AsyncMock()
        semantic.add_relation = AsyncMock()
        semantic.find_entities = AsyncMock(return_value=[])
        semantic.get_relations = AsyncMock(return_value=[])

        skill_store = AsyncMock()
        skill_store.get_skill = AsyncMock(return_value=None)
        skill_store.find_matching_skills = AsyncMock(return_value=[])
        skill_store.list_skills = AsyncMock(return_value=[])

        return SmartRetriever(
            embedding_service=embedding,
            episodic_memory=episodic,
            semantic_memory=semantic,
            skill_store=skill_store,
        )

    @pytest.mark.asyncio
    async def test_retrieve_skills_empty(self):
        retriever = self._make_retriever(embedding_available=False)
        results = await retriever.retrieve_skills("test query")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_retrieve_skills_kg_match(self):
        retriever = self._make_retriever(embedding_available=False)
        # Mock KG returning a domain entity that links to a skill
        domain = MagicMock(id="domain:kubernetes", weight=1.0)
        retriever._semantic.find_entities = AsyncMock(return_value=[domain])
        relation = MagicMock(
            source_id="domain:kubernetes",
            target_id="skill:pod_check",
            weight=1.0,
        )
        retriever._semantic.get_relations = AsyncMock(return_value=[relation])

        skill = MagicMock()
        skill.name = "pod_check"
        skill.prompt_template = "Check pods"
        retriever._skill_store.get_skill = AsyncMock(return_value=skill)

        results = await retriever.retrieve_skills("kubernetes health")
        assert len(results) >= 1
        assert results[0].skill.name == "pod_check"
        assert results[0].source == "kg"

    @pytest.mark.asyncio
    async def test_retrieve_skills_vector_match(self):
        retriever = self._make_retriever(embedding_available=True)
        # Mock in-memory vector search
        note = MagicMock()
        note.tags = ["skill:vm_check"]
        note.embedding = [0.2] * 384
        retriever._episodic.get_all_notes = AsyncMock(return_value=[note])
        retriever._embedding.cosine_similarity = MagicMock(return_value=0.9)

        skill = MagicMock()
        skill.name = "vm_check"
        skill.prompt_template = "Check VMs"
        retriever._skill_store.get_skill = AsyncMock(return_value=skill)

        results = await retriever.retrieve_skills("virtual machine status")
        assert len(results) >= 1
        assert results[0].source == "vector"

    @pytest.mark.asyncio
    async def test_token_budget_limits(self):
        retriever = self._make_retriever(embedding_available=False)
        # Setup keyword fallback with skills
        skill1 = MagicMock()
        skill1.name = "s1"
        skill1.prompt_template = "x" * 4000  # ~1000 tokens
        skill2 = MagicMock()
        skill2.name = "s2"
        skill2.prompt_template = "y" * 4000  # ~1000 tokens
        skill3 = MagicMock()
        skill3.name = "s3"
        skill3.prompt_template = "z" * 4000  # ~1000 tokens
        retriever._skill_store.find_matching_skills = AsyncMock(
            return_value=[skill1, skill2, skill3],
        )

        results = await retriever.retrieve_skills("test", token_budget=1500)
        total_tokens = sum(r.token_estimate for r in results)
        assert total_tokens <= 1500

    @pytest.mark.asyncio
    async def test_index_skill(self):
        retriever = self._make_retriever(embedding_available=False)
        skill = MagicMock()
        skill.name = "test_skill"
        skill.description = "A test skill"
        skill.prompt_template = "Do test"
        skill.trigger_keywords = ["test", "verify"]

        await retriever.index_skill(skill)
        retriever._episodic.add_note.assert_called_once()
        # Should create skill entity + 2 domain entities
        assert retriever._semantic.add_entity.call_count >= 3

    @pytest.mark.asyncio
    async def test_index_task_result(self):
        retriever = self._make_retriever(embedding_available=False)
        await retriever.index_task_result(
            "k8s_expert", "Check pods", "All healthy", True,
        )
        retriever._episodic.add_note.assert_called_once()
        # Should create role entity + task entity + 1 relation
        assert retriever._semantic.add_entity.call_count >= 2
        assert retriever._semantic.add_relation.call_count >= 1

    @pytest.mark.asyncio
    async def test_retrieve_context_empty(self):
        retriever = self._make_retriever(embedding_available=False)
        results = await retriever.retrieve_context("test query")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_keyword_fallback(self):
        retriever = self._make_retriever(embedding_available=False)
        skill = MagicMock()
        skill.name = "fallback_skill"
        skill.prompt_template = "Fallback prompt"
        retriever._skill_store.find_matching_skills = AsyncMock(
            return_value=[skill],
        )

        results = await retriever.retrieve_skills("anything")
        assert len(results) == 1
        assert results[0].source == "keyword"

    @pytest.mark.asyncio
    async def test_extract_skill_name_from_tags(self):
        assert (
            SmartRetriever._extract_skill_name_from_tags(["skill:pod_check"])
            == "pod_check"
        )
        assert SmartRetriever._extract_skill_name_from_tags(["other"]) is None
        assert SmartRetriever._extract_skill_name_from_tags(None) is None
        assert SmartRetriever._extract_skill_name_from_tags([]) is None
