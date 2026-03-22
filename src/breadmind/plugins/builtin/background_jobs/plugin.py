"""Long-running background job management plugin."""

from __future__ import annotations

import logging
from typing import Any, Callable

from breadmind.plugins.protocol import BaseToolPlugin
from breadmind.tools.registry import tool

logger = logging.getLogger(__name__)


class BackgroundJobsPlugin(BaseToolPlugin):
    """Plugin providing the run_background tool."""

    name = "background-jobs"
    version = "0.1.0"

    def __init__(self) -> None:
        self._bg_job_manager: Any | None = None
        self._tools: list[Callable] = []

    async def setup(self, container: Any) -> None:
        self._bg_job_manager = container.get_optional("bg_job_manager")
        self._tools = self._build_tools()

    def _build_tools(self) -> list[Callable]:
        bg_job_manager = self._bg_job_manager

        @tool(
            description=(
                "Start a long-running background job. Use for tasks that take more than "
                "a few minutes (e.g., scanning multiple servers, overnight monitoring). "
                "Provide title, job_type ('single' or 'monitor'), steps (list of step "
                "descriptions), tools_needed (list of tool names)."
            )
        )
        async def run_background(
            title: str,
            job_type: str = "single",
            steps: str = "",
            tools_needed: str = "",
            monitor_config: str = "",
        ) -> str:
            import json as _json

            if not bg_job_manager:
                return "Background job system not available. Ensure Redis and Celery are configured."

            # Parse JSON string args from LLM
            step_list = (
                _json.loads(steps)
                if isinstance(steps, str) and steps.strip().startswith("[")
                else []
            )
            tool_list = (
                _json.loads(tools_needed)
                if isinstance(tools_needed, str) and tools_needed.strip().startswith("[")
                else []
            )
            monitor_cfg = (
                _json.loads(monitor_config)
                if isinstance(monitor_config, str) and monitor_config.strip().startswith("{")
                else {}
            )

            execution_plan = []
            if job_type == "single" and step_list:
                for i, desc in enumerate(step_list):
                    t = (
                        tool_list[i]
                        if tool_list and i < len(tool_list)
                        else (tool_list[0] if tool_list else "shell_exec")
                    )
                    execution_plan.append({
                        "step": i + 1,
                        "description": desc,
                        "tool": t,
                        "args": {},
                    })

            metadata = {}
            if monitor_cfg:
                metadata["monitor_config"] = monitor_cfg

            try:
                result = await bg_job_manager.create_job(
                    title=title,
                    description=f"Background job: {title}",
                    job_type=job_type,
                    execution_plan=execution_plan,
                    metadata=metadata,
                )
                jid = result["job_id"]
                return (
                    f"Background job '{title}' started (ID: {jid}). "
                    f"Check progress at /api/bg-jobs/{jid}"
                )
            except ValueError as e:
                return f"Failed to create background job: {e}"
            except Exception as e:
                return f"Background job system error: {e}"

        return [run_background]

    def get_tools(self) -> list[Callable]:
        return self._tools
