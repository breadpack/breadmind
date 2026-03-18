from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from breadmind.core.swarm import SwarmManager
    from breadmind.core.performance import PerformanceTracker
    from breadmind.core.skill_store import SkillStore

logger = logging.getLogger(__name__)

_COOLDOWN_SECONDS = 300
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
    """Analyzes goals, evaluates existing swarm roles, creates missing roles,
    and finds matching skills. Called before SwarmCoordinator.decompose()."""

    def __init__(
        self,
        swarm_manager: SwarmManager,
        tracker: PerformanceTracker,
        skill_store: SkillStore,
        message_handler: Callable | None = None,
    ):
        self._swarm_manager = swarm_manager
        self._tracker = tracker
        self._skill_store = skill_store
        self._message_handler = message_handler
        self._plan_cache: dict[str, tuple[float, TeamPlan]] = {}
        self._retriever = None

    def set_retriever(self, retriever):
        self._retriever = retriever

    async def build_team(self, goal: str) -> TeamPlan:
        """Analyze goal and return a TeamPlan with selected/created roles and skill injections."""
        cache_key = goal.strip().lower()
        cached = self._plan_cache.get(cache_key)
        if cached:
            cache_time, cached_plan = cached
            if time.monotonic() - cache_time < _COOLDOWN_SECONDS:
                return cached_plan

        roles_info = self._build_roles_summary()
        prompt = self._build_analysis_prompt(goal, roles_info)

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
        plan.skill_injections = await self._find_skill_injections(
            goal, plan.selected_roles + plan.created_roles
        )
        self._plan_cache[cache_key] = (time.monotonic(), plan)
        return plan

    def _build_roles_summary(self) -> str:
        """Build a summary of available roles with their performance stats."""
        lines: list[str] = []
        for role_info in self._swarm_manager.get_available_roles():
            role = role_info["role"]
            desc = role_info.get("description", "")
            stats = self._tracker.get_role_stats(role)
            if stats and stats.total_runs > 0:
                perf = (
                    f"runs={stats.total_runs}, "
                    f"success_rate={stats.success_rate:.2f}, "
                    f"avg_ms={stats.avg_duration_ms:.0f}"
                )
            else:
                perf = "no data"
            lines.append(f"- {role}: {desc} [{perf}]")
        return "\n".join(lines) if lines else "(no roles available)"

    def _build_analysis_prompt(self, goal: str, roles_info: str) -> str:
        """Build the LLM prompt requesting role assessments and creation suggestions."""
        return (
            f"You are a team composition expert. Analyze this goal and decide which roles to use.\n\n"
            f"Goal: {goal}\n\n"
            f"Available roles:\n{roles_info}\n\n"
            f"Instructions:\n"
            f"1. Assess each existing role's relevance to the goal (score 0.0–1.0).\n"
            f"2. If critical expertise is missing, suggest up to {_MAX_NEW_ROLES} new roles to create.\n\n"
            f"Response format (one directive per line):\n"
            f"ASSESS|<role_name>|<relevance_score>|<use|skip|improve>\n"
            f"CREATE|<role_name>|<description>|<system_prompt>|<keyword1,keyword2,...>\n"
            f"CREATE_NONE  (if no new roles are needed)\n\n"
            f"Rules:\n"
            f"- Score >= 0.3 with action 'use' means the role is selected.\n"
            f"- Do not create more than {_MAX_NEW_ROLES} new roles.\n"
            f"- Output ONLY the directive lines, no other text."
        )

    def _parse_response(self, goal: str, response: str) -> TeamPlan:
        """Parse LLM ASSESS/CREATE directives into a TeamPlan."""
        selected_roles: list[str] = []
        created_roles: list[str] = []
        assessments: list[RoleAssessment] = []
        new_role_count = 0

        for line in response.strip().split("\n"):
            line = line.strip()

            if line.startswith("ASSESS|"):
                parts = line.split("|")
                if len(parts) < 4:
                    continue
                role = parts[1].strip()
                try:
                    score = float(parts[2].strip())
                except ValueError:
                    score = 0.0
                action = parts[3].strip().lower()

                stats = self._tracker.get_role_stats(role)
                success_rate = stats.success_rate if stats else 0.0

                assessment = RoleAssessment(
                    role=role,
                    relevance_score=score,
                    success_rate=success_rate,
                    recommendation=action,
                )
                assessments.append(assessment)

                if action == "use" and score > 0.3:
                    selected_roles.append(role)

            elif line.startswith("CREATE|") and new_role_count < _MAX_NEW_ROLES:
                parts = line.split("|")
                if len(parts) < 4:
                    continue
                role_name = parts[1].strip()
                description = parts[2].strip()
                system_prompt = parts[3].strip()
                parts[4].strip() if len(parts) > 4 else ""

                if not role_name:
                    continue

                try:
                    self._swarm_manager.add_role(
                        name=role_name,
                        system_prompt=system_prompt,
                        description=description,
                        source="auto",
                    )
                    created_roles.append(role_name)
                    new_role_count += 1
                    logger.info(f"TeamBuilder created new role '{role_name}' for goal: {goal[:50]}")
                except Exception as e:
                    logger.warning(f"TeamBuilder failed to create role '{role_name}': {e}")

        # Fallback: if nothing was selected, use "general"
        if not selected_roles and not created_roles:
            logger.info("TeamBuilder: no roles selected, falling back to 'general'")
            selected_roles = ["general"]

        reasoning = (
            f"Assessed {len(assessments)} roles, selected {len(selected_roles)}, "
            f"created {len(created_roles)} new role(s)."
        )

        return TeamPlan(
            goal=goal,
            selected_roles=selected_roles,
            created_roles=created_roles,
            reasoning=reasoning,
        )

    async def _find_skill_injections(
        self, goal: str, roles: list[str]
    ) -> dict[str, list[str]]:
        """Find matching skills for the goal and distribute them to all provided roles."""
        injections: dict[str, list[str]] = {}
        if not roles:
            return injections

        if self._retriever:
            try:
                scored = await self._retriever.retrieve_skills(goal, token_budget=2000, limit=5)
                if scored:
                    skill_prompts = [s.skill.prompt_template for s in scored if s.score > 0.3 and s.skill.prompt_template]
                    for role in roles:
                        injections[role] = skill_prompts
                    return injections
            except Exception as e:
                logger.warning(f"SmartRetriever failed in TeamBuilder: {e}")

        # Fallback: existing keyword matching
        try:
            matching_skills = await self._skill_store.find_matching_skills(goal, limit=5)
        except Exception as e:
            logger.warning(f"TeamBuilder skill lookup failed: {e}")
            return injections

        if not matching_skills:
            return injections

        skill_prompts = [s.prompt_template for s in matching_skills if s.prompt_template]
        for role in roles:
            injections[role] = skill_prompts

        return injections
