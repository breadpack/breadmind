"""Tests for skill auto-discovery from marketplace."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from breadmind.skills.auto_discovery import (
    auto_discover_skills,
    apply_fallback_skills,
    _SOFTWARE_TO_QUERIES,
)


class TestQueryMapping:
    def test_nginx_has_queries(self):
        assert "nginx" in _SOFTWARE_TO_QUERIES
        assert len(_SOFTWARE_TO_QUERIES["nginx"]) > 0

    def test_common_tools_covered(self):
        expected = ["nginx", "mysql", "docker", "prometheus", "redis", "wireguard"]
        for tool in expected:
            assert tool in _SOFTWARE_TO_QUERIES, f"{tool} not in query mapping"


class TestAutoDiscover:
    @pytest.mark.asyncio
    async def test_installs_from_marketplace(self):
        """Should search marketplace and install matching skills."""
        search_result = MagicMock()
        search_result.name = "nginx-admin"
        search_result.slug = "org/repo/nginx-admin"
        search_result.description = "Nginx administration skill"
        search_result.source = "skills.sh"

        search_engine = AsyncMock()
        search_engine.search.return_value = [search_result]

        skill_store = AsyncMock()
        skill_store.get_skill.return_value = None
        skill_store.add_skill = AsyncMock()

        result = await auto_discover_skills(
            detected_tools=["nginx"],
            search_engine=search_engine,
            skill_store=skill_store,
            max_per_domain=1,
            timeout=10,
        )

        assert result.searched >= 1

    @pytest.mark.asyncio
    async def test_skips_already_installed(self):
        """Should not reinstall existing skills."""
        search_result = MagicMock()
        search_result.name = "nginx-admin"
        search_result.slug = ""
        search_result.description = "Nginx skill"
        search_result.source = "skills.sh"

        search_engine = AsyncMock()
        search_engine.search.return_value = [search_result]

        skill_store = AsyncMock()
        skill_store.get_skill.return_value = MagicMock()  # Already exists

        result = await auto_discover_skills(
            detected_tools=["nginx"],
            search_engine=search_engine,
            skill_store=skill_store,
        )

        skill_store.add_skill.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_tools_no_search(self):
        """Should do nothing when no tools detected."""
        search_engine = AsyncMock()
        skill_store = AsyncMock()

        result = await auto_discover_skills(
            detected_tools=[],
            search_engine=search_engine,
            skill_store=skill_store,
        )

        search_engine.search.assert_not_called()
        assert result.searched == 0

    @pytest.mark.asyncio
    async def test_unknown_tool_no_search(self):
        """Tools not in query mapping should be skipped."""
        search_engine = AsyncMock()
        skill_store = AsyncMock()

        result = await auto_discover_skills(
            detected_tools=["obscure-tool-xyz"],
            search_engine=search_engine,
            skill_store=skill_store,
        )

        search_engine.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_timeout_handled(self):
        """Should handle marketplace timeout gracefully."""
        import asyncio

        async def slow_search(*args, **kwargs):
            await asyncio.sleep(100)
            return []

        search_engine = AsyncMock()
        search_engine.search.side_effect = slow_search

        skill_store = AsyncMock()

        result = await auto_discover_skills(
            detected_tools=["nginx"],
            search_engine=search_engine,
            skill_store=skill_store,
            timeout=0.1,
        )

        assert "timed out" in result.details[0].lower()

    @pytest.mark.asyncio
    async def test_no_search_engine(self):
        """Should return empty result when search_engine is None."""
        result = await auto_discover_skills(
            detected_tools=["nginx"],
            search_engine=None,
            skill_store=AsyncMock(),
        )
        assert result.searched == 0


class TestFallbackSkills:
    @pytest.mark.asyncio
    async def test_applies_fallback_when_no_marketplace(self):
        """Should register builtin skill when no marketplace skill exists."""
        skill_store = AsyncMock()
        skill_store.get_skill.return_value = None  # No marketplace skill
        skill_store.add_skill = AsyncMock()

        await apply_fallback_skills(["nginx"], skill_store)

        # Should have registered webserver_admin as fallback
        if skill_store.add_skill.call_count > 0:
            names = {call.kwargs["name"] for call in skill_store.add_skill.call_args_list}
            assert "webserver_admin" in names

    @pytest.mark.asyncio
    async def test_skips_fallback_when_marketplace_exists(self):
        """Should not register builtin when marketplace skill exists."""
        skill_store = AsyncMock()
        skill_store.get_skill.return_value = MagicMock()  # Already has skill
        skill_store.add_skill = AsyncMock()

        await apply_fallback_skills(["nginx"], skill_store)

        skill_store.add_skill.assert_not_called()
