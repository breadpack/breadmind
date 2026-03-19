from __future__ import annotations

import logging
import time
from pathlib import Path

from breadmind.tools.registry import ToolResult
from breadmind.coding.adapters import get_adapter
from breadmind.coding.executors.local import LocalExecutor
from breadmind.coding.executors.remote import RemoteExecutor
from breadmind.coding.session_store import CodingSessionStore
from breadmind.coding.project_config import ProjectConfigManager

logger = logging.getLogger("breadmind.coding")


def create_code_delegate_tool(db=None, session_store=None):
    if session_store is None:
        session_store = CodingSessionStore(db=db)
    config_mgr = ProjectConfigManager()

    async def code_delegate(
        agent: str,
        project: str,
        prompt: str,
        model: str = "",
        session_id: str = "",
        remote: dict | None = None,
        timeout: int = 300,
    ) -> ToolResult:
        try:
            adapter = get_adapter(agent)
        except ValueError as exc:
            return ToolResult(success=False, output=str(exc))

        # Check project path for local execution
        if remote is None and not Path(project).is_dir():
            return ToolResult(
                success=False,
                output=f"Project directory not found: {project}",
            )

        # Log project config file if present
        config_path = config_mgr.ensure_config(project, agent)
        if config_path:
            logger.info("Using project config: %s", config_path)

        # Build options
        options: dict = {}
        if model:
            options["model"] = model
        if session_id:
            options["session_id"] = session_id
        # Do NOT auto-resume — only resume when session_id explicitly provided

        command = adapter.build_command(project, prompt, options or None)

        # Choose executor
        if remote:
            executor: LocalExecutor | RemoteExecutor = RemoteExecutor(
                host=remote.get("host", ""),
                username=remote.get("username", ""),
                password=remote.get("password"),
            )
        else:
            executor = LocalExecutor()

        # Execute
        t0 = time.monotonic()
        exec_result = await executor.run(command, cwd=project, timeout=timeout)
        elapsed = time.monotonic() - t0

        # Parse result
        coding_result = adapter.parse_result(
            exec_result.stdout, exec_result.stderr, exec_result.returncode
        )
        coding_result.execution_time = elapsed
        coding_result.agent = agent

        # Persist session if available
        if coding_result.session_id:
            await session_store.save_session(
                project, agent, coding_result.session_id, prompt[:100]
            )

        # Format output
        output_parts: list[str] = []
        if coding_result.success:
            output_parts.append(f"[{agent}] Task completed in {elapsed:.1f}s")
        else:
            output_parts.append(
                f"[{agent}] Task failed (exit code: {exec_result.returncode})"
            )
        output_parts.append(coding_result.output)
        if coding_result.files_changed:
            output_parts.append(f"Files changed: {', '.join(coding_result.files_changed)}")
        if coding_result.session_id:
            output_parts.append(f"Session: {coding_result.session_id}")

        return ToolResult(
            success=coding_result.success,
            output="\n".join(output_parts),
        )

    tool_def = {
        "name": "code_delegate",
        "description": (
            "Delegate a coding task to an external coding agent. "
            "Supports Claude Code, Codex, and Gemini CLI. "
            "Use when the user asks to write code, implement features, fix bugs, "
            "refactor, write tests, or any software development task. "
            "Keywords: 코드, 구현, 개발, 리팩토링, 버그, 테스트, code, implement, refactor, fix, develop."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "enum": ["claude", "codex", "gemini"],
                    "description": "Which coding agent to use",
                },
                "project": {
                    "type": "string",
                    "description": "Absolute path to the project directory",
                },
                "prompt": {
                    "type": "string",
                    "description": "The coding task description to delegate",
                },
                "model": {
                    "type": "string",
                    "description": "Model override (optional)",
                },
                "session_id": {
                    "type": "string",
                    "description": "Resume a previous session (optional)",
                },
                "remote": {
                    "type": "object",
                    "properties": {
                        "host": {"type": "string"},
                        "username": {"type": "string"},
                        "password": {"type": "string"},
                    },
                    "description": "SSH remote config (optional, null=local)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 300)",
                },
            },
            "required": ["agent", "project", "prompt"],
        },
    }

    return tool_def, code_delegate
