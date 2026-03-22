"""Coding Job Executor — runs phased coding tasks as background jobs.

Executes a CodingPlan as a series of code_delegate calls with
session resumption between phases and Channel supervision.
Can run standalone (async) or be dispatched via BackgroundJobManager.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

logger = logging.getLogger("breadmind.coding.job_executor")


class CodingJobExecutor:
    """Executes a phased coding plan with session resumption and supervision."""

    def __init__(
        self,
        provider: Any = None,
        db: Any = None,
        notify_callback: Any = None,
    ):
        self._provider = provider
        self._db = db
        self._notify_callback = notify_callback
        # JobTracker integration
        from breadmind.coding.job_tracker import JobTracker
        self._tracker = JobTracker.get_instance()

    async def execute_plan(
        self,
        plan_data: dict,
        job_id: str = "",
        store: Any = None,
        publish_fn: Any = None,
    ) -> dict:
        """Execute a coding plan step by step.

        Args:
            plan_data: Dict with keys: project, agent, model, phases[], original_prompt
            job_id: Background job ID (for progress updates)
            store: BgJobsStore for persisting progress
            publish_fn: Redis publish function for real-time updates

        Returns:
            Summary dict with results per phase.
        """
        project = plan_data["project"]
        agent = plan_data.get("agent", "claude")
        model = plan_data.get("model", "")
        phases = plan_data.get("phases", [])
        original_prompt = plan_data.get("original_prompt", "")

        if not phases:
            return {"success": False, "error": "No phases in plan"}

        # Register with JobTracker
        if not job_id:
            import uuid
            job_id = str(uuid.uuid4())[:8]
        self._tracker.create_job(
            job_id=job_id, project=project, agent=agent,
            prompt=original_prompt,
        )
        self._tracker.set_decomposing(job_id)
        self._tracker.set_phases(job_id, phases)

        from breadmind.coding.adapters import get_adapter
        from breadmind.coding.executors.local import LocalExecutor
        from breadmind.coding.channel_supervisor import ChannelSupervisor

        try:
            adapter = get_adapter(agent)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        executor = LocalExecutor()
        session_id = ""  # Will be populated after first phase
        results = []
        total = len(phases)
        t0 = time.monotonic()

        for i, phase in enumerate(phases):
            step_num = phase.get("step", i + 1)
            title = phase.get("title", f"Phase {step_num}")
            prompt = phase.get("prompt", "")
            timeout = phase.get("timeout", 300)

            # Progress update
            pct = int((i / total) * 100)
            if store and job_id:
                await store.update_progress(job_id, i, f"Phase {step_num}: {title}", pct)
            if publish_fn:
                publish_fn(job_id, {
                    "type": "progress",
                    "phase": step_num,
                    "total_phases": total,
                    "title": title,
                    "percentage": pct,
                })
            if self._notify_callback:
                await self._notify_callback(step_num, "started", title)
            self._tracker.start_phase(job_id, step_num)

            # Build command with session resumption
            options: dict = {}
            if model:
                options["model"] = model
            if session_id:
                options["session_id"] = session_id

            command = adapter.build_command(project, prompt, options or None)

            # Start Channel supervisor for this phase
            supervisor = None
            try:
                supervisor = ChannelSupervisor(
                    provider=self._provider,
                    max_auto_retries=3,
                )
                sup_port, ch_port = await supervisor.start(
                    session_id=f"{job_id or 'local'}-phase-{step_num}",
                    project=project,
                    prompt=prompt,
                )

                # Write .mcp.json
                mcp_config = supervisor.get_mcp_config_entry()
                import json as _json
                from pathlib import Path
                mcp_json_path = Path(project) / ".mcp.json"
                mcp_existed = mcp_json_path.exists()
                mcp_backup = None

                if mcp_existed:
                    existing = _json.loads(mcp_json_path.read_text(encoding="utf-8"))
                    mcp_backup = _json.dumps(existing, indent=2)
                    servers = existing.get("mcpServers", {})
                    servers["breadmind-channel"] = mcp_config
                    existing["mcpServers"] = servers
                    mcp_json_path.write_text(_json.dumps(existing, indent=2), encoding="utf-8")
                else:
                    mcp_json_path.write_text(
                        _json.dumps({"mcpServers": {"breadmind-channel": mcp_config}}, indent=2),
                        encoding="utf-8",
                    )

                command += [
                    "--channels", "server:breadmind-channel",
                    "--dangerously-load-development-channels", "server:breadmind-channel",
                ]
            except Exception as e:
                logger.warning("Channel setup failed for phase %d: %s", step_num, e)
                supervisor = None

            # Execute phase
            try:
                exec_result = await executor.run(command, cwd=project, timeout=timeout)

                # Parse result for session ID
                coding_result = adapter.parse_result(
                    exec_result.stdout, exec_result.stderr, exec_result.returncode,
                )

                # Capture session ID for resumption
                if coding_result.session_id:
                    session_id = coding_result.session_id

                # Get supervisor report
                report_text = ""
                if supervisor:
                    try:
                        report = await supervisor.stop()
                        report_text = report.summary
                    except Exception:
                        pass

                phase_result = {
                    "step": step_num,
                    "title": title,
                    "success": coding_result.success,
                    "output": report_text or coding_result.output[:2000],
                    "files_changed": coding_result.files_changed,
                    "session_id": coding_result.session_id or "",
                }
                results.append(phase_result)
                self._tracker.complete_phase(
                    job_id, step_num, coding_result.success,
                    output=report_text or coding_result.output[:500],
                    files_changed=coding_result.files_changed,
                )

                if publish_fn:
                    publish_fn(job_id, {
                        "type": "phase_complete",
                        "phase": step_num,
                        "success": coding_result.success,
                        "title": title,
                    })

                # If phase failed, decide whether to continue
                if not coding_result.success:
                    logger.warning("Phase %d failed: %s", step_num, coding_result.output[:200])
                    if self._notify_callback:
                        await self._notify_callback(step_num, "failed", coding_result.output[:500])
                    # Continue to next phase — the resumed session may recover

            except Exception as e:
                results.append({
                    "step": step_num,
                    "title": title,
                    "success": False,
                    "output": f"Execution error: {e}",
                    "files_changed": [],
                })
                self._tracker.complete_phase(job_id, step_num, False, output=str(e))
                logger.error("Phase %d execution error: %s", step_num, e)
            finally:
                # Cleanup .mcp.json
                if supervisor:
                    try:
                        from pathlib import Path
                        mcp_json_path = Path(project) / ".mcp.json"
                        if mcp_backup is not None:
                            mcp_json_path.write_text(mcp_backup, encoding="utf-8")
                        elif not mcp_existed:
                            mcp_json_path.unlink(missing_ok=True)
                    except Exception:
                        pass

        # Final summary
        elapsed = time.monotonic() - t0
        success_count = sum(1 for r in results if r["success"])
        all_files = []
        for r in results:
            all_files.extend(r.get("files_changed", []))

        summary = {
            "success": success_count == total,
            "phases_completed": f"{success_count}/{total}",
            "total_duration_seconds": round(elapsed, 1),
            "files_changed": list(set(all_files)),
            "session_id": session_id,
            "results": results,
        }

        # Update JobTracker
        self._tracker.complete_job(
            job_id,
            success=success_count == total,
            session_id=session_id,
        )

        # Update job store
        if store and job_id:
            result_text = json.dumps(summary, ensure_ascii=False, indent=2)
            status = "completed" if success_count == total else "failed"
            await store.update_status(job_id, status, result=result_text)
            await store.update_progress(job_id, total, "Completed", 100)

        if publish_fn:
            publish_fn(job_id, {"type": "completed", "summary": summary})

        return summary
