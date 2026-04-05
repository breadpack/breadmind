"""Tests for skill_marketplace module."""
from __future__ import annotations

import pytest

from breadmind.skills.skill_marketplace import (
    MarketplaceSkill,
    SkillCategory,
    SkillMarketplace,
    SkillRating,
    SkillVersion,
    _parse_semver,
)


def _make_skill(
    name: str = "test-skill",
    slug: str = "test-skill",
    description: str = "A test skill",
    category: SkillCategory = SkillCategory.OTHER,
    **kwargs,
) -> MarketplaceSkill:
    return MarketplaceSkill(
        name=name, slug=slug, description=description, category=category, **kwargs
    )


class TestMarketplaceSkill:
    def test_average_rating_empty(self):
        skill = _make_skill()
        assert skill.average_rating == 0.0

    def test_average_rating_calculated(self):
        skill = _make_skill(
            ratings=[
                SkillRating(user_id="u1", score=5),
                SkillRating(user_id="u2", score=3),
            ]
        )
        assert skill.average_rating == 4.0

    def test_rating_count(self):
        skill = _make_skill(
            ratings=[
                SkillRating(user_id="u1", score=4),
                SkillRating(user_id="u2", score=2),
                SkillRating(user_id="u3", score=5),
            ]
        )
        assert skill.rating_count == 3


class TestSkillMarketplace:
    def test_register_and_get(self):
        mp = SkillMarketplace()
        skill = _make_skill()
        mp.register(skill)
        assert mp.get_skill("test-skill") is skill

    def test_register_duplicate_raises(self):
        mp = SkillMarketplace()
        mp.register(_make_skill())
        with pytest.raises(ValueError, match="already exists"):
            mp.register(_make_skill())

    def test_get_nonexistent_returns_none(self):
        mp = SkillMarketplace()
        assert mp.get_skill("nope") is None

    def test_search_by_query(self):
        mp = SkillMarketplace()
        mp.register(_make_skill(name="Docker Manager", slug="docker-mgr", description="Manage docker containers"))
        mp.register(_make_skill(name="Git Helper", slug="git-helper", description="Git workflow tools"))
        results = mp.search(query="docker")
        assert len(results) == 1
        assert results[0].slug == "docker-mgr"

    def test_search_by_category(self):
        mp = SkillMarketplace()
        mp.register(_make_skill(slug="s1", category=SkillCategory.DEVOPS))
        mp.register(_make_skill(slug="s2", category=SkillCategory.CODING))
        mp.register(_make_skill(slug="s3", category=SkillCategory.DEVOPS))
        results = mp.search(category=SkillCategory.DEVOPS)
        assert len(results) == 2

    def test_search_by_tags(self):
        mp = SkillMarketplace()
        mp.register(_make_skill(slug="s1", tags=["kubernetes", "helm"]))
        mp.register(_make_skill(slug="s2", tags=["docker"]))
        results = mp.search(tags=["kubernetes"])
        assert len(results) == 1
        assert results[0].slug == "s1"

    def test_search_by_min_rating(self):
        mp = SkillMarketplace()
        mp.register(_make_skill(slug="s1", ratings=[SkillRating(user_id="u1", score=5)]))
        mp.register(_make_skill(slug="s2", ratings=[SkillRating(user_id="u1", score=2)]))
        mp.register(_make_skill(slug="s3"))  # no ratings
        results = mp.search(min_rating=3.0)
        assert len(results) == 1
        assert results[0].slug == "s1"

    def test_search_with_limit(self):
        mp = SkillMarketplace()
        for i in range(10):
            mp.register(_make_skill(name=f"skill-{i}", slug=f"skill-{i}"))
        results = mp.search(limit=3)
        assert len(results) == 3

    def test_search_sort_by_installs(self):
        mp = SkillMarketplace()
        mp.register(_make_skill(slug="low", install_count=5))
        mp.register(_make_skill(slug="high", install_count=100))
        results = mp.search(sort_by="installs")
        assert results[0].slug == "high"

    def test_browse_category(self):
        mp = SkillMarketplace()
        mp.register(_make_skill(slug="s1", category=SkillCategory.SECURITY, install_count=10))
        mp.register(_make_skill(slug="s2", category=SkillCategory.SECURITY, install_count=50))
        mp.register(_make_skill(slug="s3", category=SkillCategory.CODING))
        results = mp.browse_category(SkillCategory.SECURITY)
        assert len(results) == 2
        assert results[0].slug == "s2"  # higher installs first

    def test_get_categories(self):
        mp = SkillMarketplace()
        mp.register(_make_skill(slug="s1", category=SkillCategory.DEVOPS))
        mp.register(_make_skill(slug="s2", category=SkillCategory.DEVOPS))
        mp.register(_make_skill(slug="s3", category=SkillCategory.DATA))
        cats = mp.get_categories()
        assert cats[SkillCategory.DEVOPS] == 2
        assert cats[SkillCategory.DATA] == 1

    def test_rate_new_rating(self):
        mp = SkillMarketplace()
        mp.register(_make_skill(slug="s1"))
        assert mp.rate("s1", "user1", 4, "Great!") is True
        skill = mp.get_skill("s1")
        assert skill.rating_count == 1
        assert skill.average_rating == 4.0

    def test_rate_updates_existing(self):
        mp = SkillMarketplace()
        mp.register(_make_skill(slug="s1"))
        mp.rate("s1", "user1", 3)
        mp.rate("s1", "user1", 5)  # update
        skill = mp.get_skill("s1")
        assert skill.rating_count == 1
        assert skill.average_rating == 5.0

    def test_rate_invalid_score(self):
        mp = SkillMarketplace()
        mp.register(_make_skill(slug="s1"))
        assert mp.rate("s1", "user1", 0) is False
        assert mp.rate("s1", "user1", 6) is False

    def test_rate_nonexistent_skill(self):
        mp = SkillMarketplace()
        assert mp.rate("nope", "user1", 5) is False

    def test_get_top_rated(self):
        mp = SkillMarketplace()
        mp.register(_make_skill(slug="low", ratings=[SkillRating(user_id="u1", score=2)]))
        mp.register(_make_skill(slug="high", ratings=[SkillRating(user_id="u1", score=5)]))
        mp.register(_make_skill(slug="none"))  # no ratings, excluded
        top = mp.get_top_rated(limit=5)
        assert len(top) == 2
        assert top[0].slug == "high"

    def test_get_trending(self):
        mp = SkillMarketplace()
        mp.register(_make_skill(slug="s1", install_count=100))
        mp.register(_make_skill(slug="s2", install_count=500))
        trending = mp.get_trending(limit=2)
        assert trending[0].slug == "s2"

    def test_mark_installed_and_uninstalled(self):
        mp = SkillMarketplace()
        mp.register(_make_skill(slug="s1"))
        assert mp.get_installed_version("s1") is None
        mp.mark_installed("s1", "1.0.0")
        assert mp.get_installed_version("s1") == "1.0.0"
        # install_count should increment
        assert mp.get_skill("s1").install_count == 1
        mp.mark_uninstalled("s1")
        assert mp.get_installed_version("s1") is None

    def test_check_update_available(self):
        mp = SkillMarketplace()
        mp.register(
            _make_skill(
                slug="s1",
                current_version="2.0.0",
                versions=[
                    SkillVersion(version="1.0.0", changelog="Initial"),
                    SkillVersion(version="2.0.0", changelog="Major update"),
                ],
            )
        )
        mp.mark_installed("s1", "1.0.0")
        update = mp.check_update("s1")
        assert update is not None
        assert update.version == "2.0.0"

    def test_check_update_none_available(self):
        mp = SkillMarketplace()
        mp.register(_make_skill(slug="s1", current_version="1.0.0"))
        mp.mark_installed("s1", "1.0.0")
        assert mp.check_update("s1") is None

    def test_check_update_not_installed(self):
        mp = SkillMarketplace()
        mp.register(_make_skill(slug="s1"))
        assert mp.check_update("s1") is None

    def test_resolve_dependencies_no_deps(self):
        mp = SkillMarketplace()
        mp.register(_make_skill(slug="s1"))
        assert mp.resolve_dependencies("s1") == ["s1"]

    def test_resolve_dependencies_chain(self):
        mp = SkillMarketplace()
        mp.register(_make_skill(slug="base"))
        mp.register(_make_skill(slug="mid", dependencies=["base"]))
        mp.register(_make_skill(slug="top", dependencies=["mid"]))
        order = mp.resolve_dependencies("top")
        assert order == ["base", "mid", "top"]

    def test_resolve_dependencies_circular_raises(self):
        mp = SkillMarketplace()
        mp.register(_make_skill(slug="a", dependencies=["b"]))
        mp.register(_make_skill(slug="b", dependencies=["a"]))
        with pytest.raises(ValueError, match="Circular dependency"):
            mp.resolve_dependencies("a")

    def test_get_popular_tags(self):
        mp = SkillMarketplace()
        mp.register(_make_skill(slug="s1", tags=["kubernetes", "devops"]))
        mp.register(_make_skill(slug="s2", tags=["kubernetes", "helm"]))
        mp.register(_make_skill(slug="s3", tags=["docker"]))
        tags = mp.get_popular_tags(limit=2)
        assert tags[0] == ("kubernetes", 2)
        assert len(tags) == 2


class TestParseSemver:
    def test_basic(self):
        assert _parse_semver("1.2.3") == (1, 2, 3)

    def test_two_part(self):
        assert _parse_semver("1.0") == (1, 0, 0)

    def test_with_prerelease(self):
        assert _parse_semver("2.0.0-beta") == (2, 0, 0)

    def test_comparison(self):
        assert _parse_semver("2.0.0") > _parse_semver("1.9.9")
