"""LLM-based initial DAG generation."""
from __future__ import annotations

import json
import re
from typing import Any

from breadmind.flow.dag import DAG, DAGValidationError, Step


class DAGGenerationError(ValueError):
    pass


DAG_SYSTEM_PROMPT = """You are a planner that generates DAGs for autonomous task execution.

Given a task, output JSON with this exact shape:
{
  "steps": [
    {
      "id": "step_id_snake_case",
      "title": "Human readable title",
      "tool": "tool_name_from_available_list",
      "args": { ... },
      "depends_on": ["other_step_id", ...]
    }
  ]
}

Rules:
- Only use tools from the provided available_tools list.
- Each step id must be unique.
- depends_on must reference earlier steps only.
- No cycles.
- Keep steps small and focused.
- Return ONLY JSON, no prose, no markdown fences.
"""


class DAGGenerator:
    def __init__(self, llm: Any) -> None:
        self._llm = llm

    async def generate(
        self,
        *,
        title: str,
        description: str,
        available_tools: list[str],
    ) -> DAG:
        user_msg = (
            f"Task title: {title}\n"
            f"Description: {description}\n"
            f"Available tools: {', '.join(available_tools)}\n"
            f"Generate the DAG now."
        )
        messages = [
            {"role": "system", "content": DAG_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]
        resp = await self._llm.chat(messages)
        text = (getattr(resp, "content", None) or "").strip()
        text = _strip_code_fences(text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DAGGenerationError(f"invalid JSON from LLM: {exc}: {text[:200]}") from exc

        steps_data = data.get("steps", [])
        if not isinstance(steps_data, list) or not steps_data:
            raise DAGGenerationError("LLM returned empty or invalid steps list")

        available = set(available_tools)
        steps: list[Step] = []
        for i, s in enumerate(steps_data):
            if not isinstance(s, dict):
                raise DAGGenerationError(f"step {i} is not an object")
            tool = s.get("tool")
            if tool is not None and tool not in available:
                raise DAGGenerationError(f"step '{s.get('id')}' uses unknown tool '{tool}'")
            try:
                steps.append(Step(
                    id=str(s["id"]),
                    title=str(s["title"]),
                    tool=tool,
                    args=dict(s.get("args", {})),
                    depends_on=list(s.get("depends_on", [])),
                    timeout_seconds=int(s.get("timeout_seconds", 300)),
                    max_attempts=int(s.get("max_attempts", 3)),
                ))
            except (KeyError, TypeError) as exc:
                raise DAGGenerationError(f"step {i} malformed: {exc}") from exc

        dag = DAG(steps=steps)
        try:
            dag.validate()
        except DAGValidationError as exc:
            raise DAGGenerationError(f"DAG invalid: {exc}") from exc
        return dag


_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _strip_code_fences(text: str) -> str:
    m = _FENCE_RE.match(text.strip())
    if m:
        return m.group(1).strip()
    return text
