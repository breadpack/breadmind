from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from pathlib import Path

from typing import Any

from breadmind.tools.registry import ToolResult
from breadmind.coding.adapters import get_adapter
from breadmind.coding.executors.local import LocalExecutor
from breadmind.coding.executors.remote import RemoteExecutor
from breadmind.coding.job_tracker import JobTracker
from breadmind.coding.session_store import CodingSessionStore
from breadmind.coding.project_config import ProjectConfigManager
from breadmind.utils.helpers import generate_short_id

logger = logging.getLogger("breadmind.coding")


def _register_job_for_delegation(
    *,
    job_id: str,
    project: str,
    agent: str,
    prompt: str,
    user: str = "",
    channel: str = "",
) -> None:
    """Register a coding job with :class:`JobTracker`, forwarding ``user``/``channel``.

    Single entry point used by ``code_delegate`` so that the dispatch-chain
    context (messenger user, channel) is consistently attached to the job
    row, enabling per-user job filtering and notification routing downstream.

    Resolution is dual-mode: in production ``JobTracker`` is the class with a
    ``get_instance()`` classmethod singleton; in tests the module-level name
    may be monkey-patched to a factory callable (``lambda: tracker``), in
    which case we fall through to direct instantiation.
    """
    if hasattr(JobTracker, "get_instance"):
        tracker = JobTracker.get_instance()
    else:
        tracker = JobTracker()
    tracker.create_job(
        job_id, project, agent, prompt, user=user, channel=channel,
    )


def _channel_available() -> bool:
    """Check if a JS runtime (Bun, tsx, or Node) is available for channel supervision."""
    return any(shutil.which(rt) for rt in ("bun", "tsx", "node"))


def _detect_available_agents() -> list[str]:
    """Detect which coding agent CLIs are installed."""
    agents = []
    for name, cmd in [("claude", "claude"), ("codex", "codex"), ("gemini", "gemini")]:
        if shutil.which(cmd):
            agents.append(name)
    return agents or ["claude"]  # fallback


def create_code_delegate_tool(db=None, session_store=None, provider=None):
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
        supervise: bool = True,
        long_running: bool = False,
    ) -> ToolResult:
        # ── Long-running mode: decompose → phased execution ──────
        if long_running and provider and remote is None:
            return await _execute_long_running(
                agent=agent, project=project, prompt=prompt,
                model=model, timeout=timeout, provider=provider, db=db,
            )

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

        # ── Channel supervision (local Claude agent only) ────────────
        use_channel = (
            supervise
            and agent == "claude"
            and remote is None
            and _channel_available()
        )

        supervisor = None
        if use_channel:
            try:
                from breadmind.coding.channel_supervisor import ChannelSupervisor

                sup_session_id = session_id or generate_short_id()
                supervisor = ChannelSupervisor(
                    provider=provider,
                    max_auto_retries=3,
                )
                sup_port, ch_port = await supervisor.start(
                    session_id=sup_session_id,
                    project=project,
                    prompt=prompt,
                )

                # Write temporary .mcp.json for channel server registration
                mcp_config = supervisor.get_mcp_config_entry()
                mcp_json_path = Path(project) / ".mcp.json"
                mcp_json_existed = mcp_json_path.exists()
                mcp_json_backup = None

                if mcp_json_existed:
                    existing = json.loads(mcp_json_path.read_text(encoding="utf-8"))
                    mcp_json_backup = json.dumps(existing, indent=2)
                    servers = existing.get("mcpServers", {})
                    servers["breadmind-channel"] = mcp_config
                    existing["mcpServers"] = servers
                    mcp_json_path.write_text(
                        json.dumps(existing, indent=2), encoding="utf-8",
                    )
                else:
                    mcp_json_path.write_text(
                        json.dumps({"mcpServers": {"breadmind-channel": mcp_config}}, indent=2),
                        encoding="utf-8",
                    )

                # Add channel flags to command
                command += [
                    "--channels", "server:breadmind-channel",
                    "--dangerously-load-development-channels", "server:breadmind-channel",
                ]

                logger.info(
                    "Channel supervision enabled: sup_port=%d ch_port=%d",
                    sup_port, ch_port,
                )
            except Exception as e:
                logger.warning("Channel supervision setup failed, continuing without: %s", e)
                supervisor = None
                use_channel = False

        # ── Execute ──────────────────────────────────────────────────
        t0 = time.monotonic()

        try:
            exec_result = await executor.run(command, cwd=project, timeout=timeout)
        finally:
            # Cleanup .mcp.json
            if use_channel:
                try:
                    mcp_json_path = Path(project) / ".mcp.json"
                    if mcp_json_backup is not None:
                        mcp_json_path.write_text(mcp_json_backup, encoding="utf-8")
                    elif not mcp_json_existed:
                        mcp_json_path.unlink(missing_ok=True)
                except Exception:
                    pass

        elapsed = time.monotonic() - t0

        # ── Stop supervisor and get report ───────────────────────────
        report_output = ""
        if supervisor:
            try:
                report = await supervisor.stop()
                report_output = report.summary
            except Exception as e:
                logger.warning("Supervisor stop failed: %s", e)

        # ── Parse result ─────────────────────────────────────────────
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

        # ── Format output ────────────────────────────────────────────
        output_parts: list[str] = []
        if coding_result.success:
            output_parts.append(f"[{agent}] Task completed in {elapsed:.1f}s")
        else:
            output_parts.append(
                f"[{agent}] Task failed (exit code: {exec_result.returncode})"
            )

        # Prefer supervisor report if available
        if report_output:
            output_parts.append(report_output)
        else:
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
            "CRITICAL: The 'prompt' parameter must contain the FULL, DETAILED specification "
            "including all context from the conversation — language (C#, Python, etc.), "
            "frameworks, architecture decisions, specific APIs to use, file structure, "
            "and implementation requirements. The coding agent has NO access to this conversation, "
            "so every detail must be in the prompt. A vague prompt like 'create a project' "
            "will produce poor results. Write the prompt as if briefing a new developer "
            "who knows nothing about the prior discussion."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "enum": _detect_available_agents(),
                    "description": "Which coding agent to use. Only installed agents are listed.",
                },
                "project": {
                    "type": "string",
                    "description": "Absolute path to the project directory",
                },
                "prompt": {
                    "type": "string",
                    "description": (
                        "DETAILED coding task description to delegate. Must include ALL context: "
                        "programming language, project type, architecture, specific APIs/libraries, "
                        "file structure, and implementation requirements. The coding agent cannot "
                        "see conversation history — include everything it needs to know."
                    ),
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
                "long_running": {
                    "type": "boolean",
                    "description": (
                        "Set to true for large projects that need multiple phases. "
                        "The task will be automatically decomposed into phases and "
                        "executed sequentially with session resumption. Use when "
                        "the project involves creating multiple files, complex "
                        "architecture, or estimated work time > 5 minutes."
                    ),
                },
            },
            "required": ["agent", "project", "prompt"],
        },
    }

    return tool_def, code_delegate


async def _execute_long_running(
    agent: str,
    project: str,
    prompt: str,
    model: str,
    timeout: int,
    provider: Any,
    db: Any,
) -> ToolResult:
    """Launch a long-running coding task in the background.

    Returns immediately with a job_id. The actual work runs as an
    asyncio background task, independent of the user's session.
    Progress is tracked via JobTracker and visible in the Monitoring tab.
    """
    job_id = generate_short_id()
    JobTracker.get_instance()

    # Ensure project directory exists
    project_path = Path(project)
    project_path.mkdir(parents=True, exist_ok=True)

    # Launch background task
    asyncio.create_task(
        _run_long_running_background(
            job_id=job_id,
            agent=agent,
            project=project,
            prompt=prompt,
            model=model,
            provider=provider,
            db=db,
        )
    )

    return ToolResult(
        success=True,
        output=(
            f"[{agent}] 장기 작업이 백그라운드에서 시작되었습니다.\n"
            f"Job ID: {job_id}\n"
            f"프로젝트: {project}\n"
            f"진행 상황은 Monitoring 탭 또는 GET /api/coding-jobs/{job_id} 에서 확인하세요.\n"
            f"작업은 세션을 닫아도 계속 실행됩니다."
        ),
    )


async def _run_long_running_background(
    job_id: str,
    agent: str,
    project: str,
    prompt: str,
    model: str,
    provider: Any,
    db: Any,
) -> None:
    """Background coroutine that runs the actual phased execution."""
    from breadmind.coding.task_decomposer import TaskDecomposer
    from breadmind.coding.job_executor import CodingJobExecutor

    try:
        # Phase 1: Decompose
        decomposer = TaskDecomposer(provider)
        plan = await decomposer.decompose(
            project=project, prompt=prompt, agent=agent, model=model,
        )

        if not plan.phases:
            _register_job_for_delegation(
                job_id=job_id, project=project, agent=agent, prompt=prompt,
            )
            tracker = JobTracker.get_instance()
            tracker.complete_job(job_id, False, error="Task decomposition produced no phases")
            return

        # Phase 2: Execute
        executor = CodingJobExecutor(provider=provider, db=db)
        plan_data = {
            "project": project,
            "agent": agent,
            "model": model,
            "original_prompt": prompt,
            "phases": [
                {"step": p.step, "title": p.title, "prompt": p.prompt, "timeout": p.timeout}
                for p in plan.phases
            ],
        }

        await executor.execute_plan(plan_data, job_id=job_id)

    except Exception as e:
        logger.error("Background long_running job %s failed: %s", job_id, e)
        tracker = JobTracker.get_instance()
        if not tracker.get_job(job_id):
            _register_job_for_delegation(
                job_id=job_id, project=project, agent=agent, prompt=prompt,
            )
        tracker.complete_job(job_id, False, error=str(e))
