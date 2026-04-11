"""Task Decomposer — breaks large coding projects into phased execution plans.

Uses the LLM to analyze a project request and produce a structured
execution plan where each phase is a code_delegate step with
session resumption support.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from breadmind.constants import THINK_BUDGET_MEDIUM

logger = logging.getLogger("breadmind.coding.decomposer")


@dataclass
class CodingPhase:
    """A single phase in a coding project execution plan."""
    step: int
    title: str
    prompt: str
    depends_on: list[int] = field(default_factory=list)
    estimated_minutes: int = 5
    timeout: int = 300


@dataclass
class CodingPlan:
    """A decomposed coding project plan."""
    project: str
    agent: str
    original_prompt: str
    phases: list[CodingPhase] = field(default_factory=list)
    model: str = ""

    def to_execution_plan(self) -> list[dict]:
        """Convert to BackgroundJobManager execution_plan format."""
        return [
            {
                "step": phase.step,
                "description": phase.title,
                "tool": "code_delegate",
                "args": {
                    "agent": self.agent,
                    "project": self.project,
                    "prompt": phase.prompt,
                    "model": self.model,
                    "timeout": phase.timeout,
                    # session_id will be filled at runtime from previous step
                },
            }
            for phase in self.phases
        ]


class TaskDecomposer:
    """Decomposes large coding tasks into phased execution plans."""

    def __init__(self, provider: Any):
        self._provider = provider

    async def decompose(
        self,
        project: str,
        prompt: str,
        agent: str = "claude",
        model: str = "",
        max_phases: int = 10,
    ) -> CodingPlan:
        """Use LLM to decompose a project into phases."""
        from breadmind.llm.base import LLMMessage

        messages = [
            LLMMessage(
                role="system",
                content=(
                    "You are a software architect. Decompose a coding project into sequential phases.\n"
                    "Each phase should be a self-contained unit of work that builds on the previous.\n\n"
                    "Rules:\n"
                    "- Phase 1 should always be project setup/initialization\n"
                    "- Each phase should be completable in 5-15 minutes by a coding agent\n"
                    "- Later phases can depend on earlier ones (session will be resumed)\n"
                    "- Each phase prompt must be DETAILED and self-contained\n"
                    "- Include the programming language, framework, specific files to create/modify\n"
                    f"- Maximum {max_phases} phases\n\n"
                    "Respond with ONLY a JSON array:\n"
                    "[\n"
                    '  {"step": 1, "title": "...", "prompt": "DETAILED instructions...", '
                    '"estimated_minutes": 5, "timeout": 300},\n'
                    "  ...\n"
                    "]"
                ),
            ),
            LLMMessage(
                role="user",
                content=f"Project path: {project}\n\nTask:\n{prompt}",
            ),
        ]

        try:
            response = await self._provider.chat(
                messages=messages,
                think_budget=THINK_BUDGET_MEDIUM,
            )

            # Parse JSON from response
            content = response.content.strip()
            # Handle markdown code blocks
            if "```" in content:
                start = content.find("[")
                end = content.rfind("]") + 1
                if start >= 0 and end > start:
                    content = content[start:end]

            phases_data = json.loads(content)

            phases = []
            for p in phases_data[:max_phases]:
                phases.append(CodingPhase(
                    step=p.get("step", len(phases) + 1),
                    title=p.get("title", f"Phase {len(phases) + 1}"),
                    prompt=p.get("prompt", ""),
                    estimated_minutes=p.get("estimated_minutes", 5),
                    timeout=p.get("timeout", 300),
                ))

            plan = CodingPlan(
                project=project,
                agent=agent,
                original_prompt=prompt,
                phases=phases,
                model=model,
            )

            logger.info(
                "Decomposed task into %d phases for %s",
                len(phases), project,
            )
            return plan

        except Exception as e:
            logger.warning("Task decomposition failed, creating single-phase plan: %s", e)
            # Fallback: single phase with the entire prompt
            return CodingPlan(
                project=project,
                agent=agent,
                original_prompt=prompt,
                phases=[
                    CodingPhase(
                        step=1,
                        title="Full implementation",
                        prompt=prompt,
                        timeout=600,
                    )
                ],
                model=model,
            )
