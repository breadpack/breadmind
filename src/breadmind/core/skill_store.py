from __future__ import annotations

import asyncio
import logging
import os
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
    frontmatter_only: bool = False  # True = only name/description loaded
    full_loaded: bool = False  # True = prompt_template fully loaded
    file_path: str = ""  # source file for lazy loading


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
        self._retriever = None

    def set_retriever(self, retriever):
        self._retriever = retriever

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
            if self._retriever:
                try:
                    await self._retriever.index_skill(skill)
                except Exception as e:
                    logger.warning(f"Failed to index skill '{name}': {e}")
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
        if self._retriever:
            try:
                scored = await self._retriever.retrieve_skills(query, token_budget=2000, limit=limit)
                return [s.skill for s in scored]
            except Exception as e:
                logger.warning(f"SmartRetriever failed, falling back to keyword matching: {e}")
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

    async def find_matching_skills_keyword(
        self, query: str, limit: int = 3
    ) -> list[Skill]:
        """Pure keyword matching without SmartRetriever (avoids recursion)."""
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

    async def load_frontmatter_only(self, name: str, description: str,
                                      file_path: str, trigger_keywords: list[str] | None = None) -> Skill:
        """Load only skill metadata (progressive disclosure). Full content loaded on demand."""
        skill = Skill(
            name=name, description=description, prompt_template="",
            trigger_keywords=trigger_keywords or [],
            frontmatter_only=True, file_path=file_path,
        )
        async with self._lock:
            self._skills[name] = skill
        return skill

    async def load_full(self, name: str) -> Skill | None:
        """Load full skill content on demand."""
        skill = self._skills.get(name)
        if skill is None:
            return None
        if skill.full_loaded or not skill.frontmatter_only:
            return skill
        if not skill.file_path or not os.path.exists(skill.file_path):
            return skill
        try:
            with open(skill.file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            # Parse YAML frontmatter + markdown body
            if content.startswith('---'):
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    skill.prompt_template = parts[2].strip()
                else:
                    skill.prompt_template = content
            else:
                skill.prompt_template = content
            skill.full_loaded = True
            skill.frontmatter_only = False
        except (IOError, OSError):
            pass
        return skill

    def get_frontmatter_list(self) -> list[dict]:
        """Get lightweight list of all skills (name + description only) for LLM context."""
        return [{"name": s.name, "description": s.description,
                 "keywords": s.trigger_keywords}
                for s in self._skills.values()]

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
