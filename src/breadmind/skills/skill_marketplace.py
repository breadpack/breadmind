"""Enhanced skill marketplace with categories, ratings, versions, and browsing."""
from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum


class SkillCategory(str, Enum):
    CODING = "coding"
    DEVOPS = "devops"
    DATA = "data"
    SECURITY = "security"
    TESTING = "testing"
    DOCUMENTATION = "documentation"
    INFRASTRUCTURE = "infrastructure"
    COMMUNICATION = "communication"
    PRODUCTIVITY = "productivity"
    OTHER = "other"


@dataclass
class SkillVersion:
    version: str  # semver: "1.2.3"
    changelog: str = ""
    published_at: float = 0
    min_breadmind_version: str = ""


@dataclass
class SkillRating:
    user_id: str
    score: int  # 1-5
    review: str = ""
    created_at: float = 0


@dataclass
class MarketplaceSkill:
    name: str
    slug: str  # unique identifier
    description: str
    category: SkillCategory = SkillCategory.OTHER
    author: str = ""
    source_url: str = ""  # GitHub URL
    install_count: int = 0
    current_version: str = "1.0.0"
    versions: list[SkillVersion] = field(default_factory=list)
    ratings: list[SkillRating] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    registered_at: float = field(default_factory=time.time)

    @property
    def average_rating(self) -> float:
        if not self.ratings:
            return 0.0
        return sum(r.score for r in self.ratings) / len(self.ratings)

    @property
    def rating_count(self) -> int:
        return len(self.ratings)


class SkillMarketplace:
    """Enhanced skill marketplace with browse/search/rate/version support.

    Surpasses Claude Code's skill system and OpenClaw's ClawHub by providing:
    - Category-based browsing
    - Version management with changelog
    - User ratings and reviews
    - Dependency resolution
    - Install/update/rollback workflows
    """

    def __init__(self) -> None:
        self._catalog: dict[str, MarketplaceSkill] = {}
        self._installed_versions: dict[str, str] = {}  # name -> version

    def register(self, skill: MarketplaceSkill) -> None:
        """Register a skill in the marketplace catalog."""
        if skill.slug in self._catalog:
            raise ValueError(f"Skill with slug '{skill.slug}' already exists")
        self._catalog[skill.slug] = skill

    def search(
        self,
        query: str = "",
        category: SkillCategory | None = None,
        tags: list[str] | None = None,
        min_rating: float = 0,
        sort_by: str = "relevance",
        limit: int = 20,
    ) -> list[MarketplaceSkill]:
        """Search marketplace with filters and sorting.

        sort_by: "relevance", "rating", "installs", "newest"
        """
        results = list(self._catalog.values())

        # Filter by category
        if category is not None:
            results = [s for s in results if s.category == category]

        # Filter by tags
        if tags:
            tag_set = set(t.lower() for t in tags)
            results = [
                s for s in results if tag_set & set(t.lower() for t in s.tags)
            ]

        # Filter by minimum rating
        if min_rating > 0:
            results = [s for s in results if s.average_rating >= min_rating]

        # Filter / score by query
        if query:
            scored: list[tuple[float, MarketplaceSkill]] = []
            query_lower = query.lower()
            query_words = set(query_lower.split())
            for skill in results:
                score = 0.0
                name_lower = skill.name.lower()
                desc_lower = skill.description.lower()
                # Exact substring match in name is strongest signal
                if query_lower in name_lower:
                    score += 10.0
                # Exact substring in description
                if query_lower in desc_lower:
                    score += 5.0
                # Word-level matches
                name_words = set(name_lower.split())
                desc_words = set(desc_lower.split())
                tag_words = set(t.lower() for t in skill.tags)
                score += len(query_words & name_words) * 3.0
                score += len(query_words & desc_words) * 1.0
                score += len(query_words & tag_words) * 2.0
                if score > 0:
                    scored.append((score, skill))
            scored.sort(key=lambda x: x[0], reverse=True)
            results = [s for _, s in scored]
        else:
            # No query — apply sorting
            results = self._sort_skills(results, sort_by)

        return results[:limit]

    def browse_category(
        self, category: SkillCategory, limit: int = 20
    ) -> list[MarketplaceSkill]:
        """Browse skills in a specific category, sorted by installs."""
        results = [s for s in self._catalog.values() if s.category == category]
        results.sort(key=lambda s: s.install_count, reverse=True)
        return results[:limit]

    def get_skill(self, slug: str) -> MarketplaceSkill | None:
        """Get a skill by its slug."""
        return self._catalog.get(slug)

    def get_categories(self) -> dict[SkillCategory, int]:
        """Return category -> count mapping."""
        counts: dict[SkillCategory, int] = {}
        for skill in self._catalog.values():
            counts[skill.category] = counts.get(skill.category, 0) + 1
        return counts

    def rate(self, slug: str, user_id: str, score: int, review: str = "") -> bool:
        """Rate a skill (1-5). Updates existing rating if user already rated."""
        skill = self._catalog.get(slug)
        if skill is None:
            return False
        if not (1 <= score <= 5):
            return False

        # Update existing rating or add new one
        for existing in skill.ratings:
            if existing.user_id == user_id:
                existing.score = score
                existing.review = review
                existing.created_at = time.time()
                return True

        skill.ratings.append(
            SkillRating(
                user_id=user_id,
                score=score,
                review=review,
                created_at=time.time(),
            )
        )
        return True

    def get_top_rated(self, limit: int = 10) -> list[MarketplaceSkill]:
        """Return skills sorted by average rating (descending)."""
        rated = [s for s in self._catalog.values() if s.ratings]
        rated.sort(key=lambda s: s.average_rating, reverse=True)
        return rated[:limit]

    def get_trending(self, limit: int = 10) -> list[MarketplaceSkill]:
        """Skills with most installs."""
        skills = list(self._catalog.values())
        skills.sort(key=lambda s: s.install_count, reverse=True)
        return skills[:limit]

    def check_update(self, name: str) -> SkillVersion | None:
        """Check if an update is available for an installed skill."""
        installed_ver = self._installed_versions.get(name)
        if installed_ver is None:
            return None

        skill = self._catalog.get(name)
        if skill is None:
            return None

        if not skill.versions:
            # Compare with current_version
            if skill.current_version != installed_ver:
                return SkillVersion(version=skill.current_version)
            return None

        # Find the latest version
        latest = max(skill.versions, key=lambda v: _parse_semver(v.version))
        if _parse_semver(latest.version) > _parse_semver(installed_ver):
            return latest
        return None

    def get_installed_version(self, name: str) -> str | None:
        """Get the installed version of a skill."""
        return self._installed_versions.get(name)

    def mark_installed(self, name: str, version: str = "1.0.0") -> None:
        """Mark a skill as installed with given version."""
        self._installed_versions[name] = version
        skill = self._catalog.get(name)
        if skill is not None:
            skill.install_count += 1

    def mark_uninstalled(self, name: str) -> None:
        """Mark a skill as uninstalled."""
        self._installed_versions.pop(name, None)

    def resolve_dependencies(self, slug: str) -> list[str]:
        """Return ordered list of slugs to install (dependencies first).

        Uses depth-first topological sort. Raises ValueError on circular deps.
        """
        visited: set[str] = set()
        in_stack: set[str] = set()
        order: list[str] = []

        def _visit(s: str) -> None:
            if s in in_stack:
                raise ValueError(f"Circular dependency detected involving '{s}'")
            if s in visited:
                return
            in_stack.add(s)
            skill = self._catalog.get(s)
            if skill is not None:
                for dep in skill.dependencies:
                    _visit(dep)
            in_stack.remove(s)
            visited.add(s)
            order.append(s)

        _visit(slug)
        return order

    def get_popular_tags(self, limit: int = 20) -> list[tuple[str, int]]:
        """Return most popular tags with counts."""
        counter: Counter[str] = Counter()
        for skill in self._catalog.values():
            for tag in skill.tags:
                counter[tag.lower()] += 1
        return counter.most_common(limit)

    @staticmethod
    def _sort_skills(
        skills: list[MarketplaceSkill], sort_by: str
    ) -> list[MarketplaceSkill]:
        """Sort skills by the given criterion."""
        if sort_by == "rating":
            return sorted(skills, key=lambda s: s.average_rating, reverse=True)
        elif sort_by == "installs":
            return sorted(skills, key=lambda s: s.install_count, reverse=True)
        elif sort_by == "newest":
            return sorted(skills, key=lambda s: s.registered_at, reverse=True)
        # "relevance" or default — keep original order
        return skills


def _parse_semver(version: str) -> tuple[int, ...]:
    """Parse a semver string into a comparable tuple."""
    parts = re.split(r"[.\-]", version)
    result: list[int] = []
    for p in parts:
        try:
            result.append(int(p))
        except ValueError:
            break
    # Pad to at least 3 components
    while len(result) < 3:
        result.append(0)
    return tuple(result)
