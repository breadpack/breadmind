"""Channel Supervisor — monitors and guides Claude Code sessions via Channel MCP.

Spawns a Bun-based Channel MCP server alongside Claude Code, receives events
from the coding session, uses LLM to judge and auto-respond, and produces
a final summary report.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiohttp import web

logger = logging.getLogger("breadmind.coding.channel")

CHANNEL_SERVER_DIR = Path(__file__).resolve().parent.parent / "plugins" / "builtin" / "coding" / "channel-server"


@dataclass
class ChannelEvent:
    """A single event received from Claude Code via the channel."""
    event_type: str  # files_changed, test_result, approval_needed, direction_check, completed, error
    details: str
    files_changed: list[str] = field(default_factory=list)
    error: str | None = None
    raw_content: str = ""
    timestamp: str = ""


@dataclass
class SupervisorAction:
    """Decision made by the supervisor LLM."""
    action: str  # continue, reply, notify_user, abort
    message: str = ""


@dataclass
class SessionReport:
    """Final report for a supervised coding session."""
    session_id: str
    project: str
    original_prompt: str
    events: list[ChannelEvent] = field(default_factory=list)
    total_files_changed: list[str] = field(default_factory=list)
    test_results: dict = field(default_factory=dict)
    duration_seconds: float = 0
    success: bool = True
    summary: str = ""


def _find_free_port() -> int:
    """Find a free TCP port on localhost."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ChannelSupervisor:
    """Supervises a Claude Code session through the Channel MCP protocol."""

    def __init__(self, provider: Any = None, max_auto_retries: int = 3):
        self._provider = provider
        self._max_auto_retries = max_auto_retries
        self._events: list[ChannelEvent] = []
        self._session_id: str = ""
        self._original_prompt: str = ""
        self._project: str = ""
        self._supervisor_port: int = 0
        self._channel_port: int = 0
        self._channel_process: asyncio.subprocess.Process | None = None
        self._http_runner: web.AppRunner | None = None
        self._running = False
        self._start_time: float = 0
        self._consecutive_test_failures: int = 0
        self._notify_callback: Any = None  # async callback(event, action) for user notification

    async def start(
        self,
        session_id: str,
        project: str,
        prompt: str,
        notify_callback: Any = None,
    ) -> tuple[int, int]:
        """Start the channel supervisor and spawn the Bun channel server.

        Returns (supervisor_port, channel_port).
        """
        self._session_id = session_id
        self._project = project
        self._original_prompt = prompt
        self._notify_callback = notify_callback
        self._start_time = time.monotonic()
        self._running = True

        # Find free ports
        self._supervisor_port = _find_free_port()
        self._channel_port = _find_free_port()

        # Start HTTP server for receiving events
        await self._start_http_server()

        # Spawn Bun channel server
        await self._spawn_channel_server()

        logger.info(
            "ChannelSupervisor started: session=%s supervisor_port=%d channel_port=%d",
            session_id, self._supervisor_port, self._channel_port,
        )

        return self._supervisor_port, self._channel_port

    async def _start_http_server(self) -> None:
        """Start aiohttp server for receiving events from the channel."""
        app = web.Application()
        app.router.add_post("/event", self._handle_event)
        app.router.add_post("/channel-ready", self._handle_ready)
        app.router.add_get("/health", self._handle_health)

        self._http_runner = web.AppRunner(app)
        await self._http_runner.setup()
        site = web.TCPSite(self._http_runner, "127.0.0.1", self._supervisor_port)
        await site.start()

    async def _spawn_channel_server(self) -> None:
        """Spawn the Channel MCP server as a subprocess (Bun or Node)."""
        runtime, script = self._resolve_runtime()
        if not runtime:
            logger.warning("No JS runtime (bun/node) found, channel supervision disabled")
            return

        env = {
            **os.environ,
            "BREADMIND_SUPERVISOR_PORT": str(self._supervisor_port),
            "CHANNEL_PORT": str(self._channel_port),
            "SESSION_ID": self._session_id,
        }
        # Remove ANTHROPIC_API_KEY so Claude Code uses local OAuth
        env.pop("ANTHROPIC_API_KEY", None)

        # Install dependencies if needed
        node_modules = CHANNEL_SERVER_DIR / "node_modules"
        if not node_modules.exists():
            npm = shutil.which("npm")
            if npm:
                install_proc = await asyncio.create_subprocess_exec(
                    npm, "install", "--production",
                    cwd=str(CHANNEL_SERVER_DIR),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await install_proc.communicate()

        self._channel_process = await asyncio.create_subprocess_exec(
            runtime, str(script),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info("Channel server spawned: PID=%s runtime=%s", self._channel_process.pid, runtime)

    @staticmethod
    def _resolve_runtime() -> tuple[str | None, Path | None]:
        """Find Bun or Node runtime and matching script."""
        bun = shutil.which("bun")
        if bun:
            return bun, CHANNEL_SERVER_DIR / "channel.ts"
        node = shutil.which("node")
        # For Node, we need the compiled JS (or use tsx)
        tsx = shutil.which("tsx")
        if tsx:
            return tsx, CHANNEL_SERVER_DIR / "channel.ts"
        if node:
            js_path = CHANNEL_SERVER_DIR / "channel.js"
            if js_path.exists():
                return node, js_path
            # Try ts with node --loader
            return node, CHANNEL_SERVER_DIR / "channel.ts"
        return None, None

    # ── HTTP Handlers ────────────────────────────────────────────────────

    async def _handle_event(self, request: web.Request) -> web.Response:
        """Receive an event from Claude Code via the channel server."""
        try:
            data = await request.json()
            content = data.get("content", "")

            # Parse structured event from content
            event = self._parse_event(content, data.get("timestamp", ""))
            self._events.append(event)

            # Track files
            if event.files_changed:
                for f in event.files_changed:
                    if f not in self._report_files:
                        self._report_files.append(f)

            # Auto-judge the event
            action = await self._judge_event(event)

            # Execute the action
            if action.action == "reply":
                await self.send_reply(action.message)
            elif action.action == "notify_user" and self._notify_callback:
                await self._notify_callback(event, action)
            elif action.action == "abort":
                await self.send_reply("BreadMind: 작업을 중단합니다. " + action.message)
                self._running = False

            return web.json_response({"ok": True, "action": action.action})
        except Exception as e:
            logger.error("Event handling error: %s", e)
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_ready(self, request: web.Request) -> web.Response:
        """Channel server signals it's ready."""
        logger.info("Channel server ready for session %s", self._session_id)
        return web.json_response({"ok": True})

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "session_id": self._session_id})

    @property
    def _report_files(self) -> list[str]:
        if not hasattr(self, "_files_changed"):
            self._files_changed: list[str] = []
        return self._files_changed

    # ── Event Parsing ────────────────────────────────────────────────────

    def _parse_event(self, content: str, timestamp: str) -> ChannelEvent:
        """Parse raw channel content into a structured event."""
        try:
            data = json.loads(content)
            return ChannelEvent(
                event_type=data.get("event_type", "unknown"),
                details=data.get("details", content),
                files_changed=data.get("files_changed", []),
                error=data.get("error"),
                raw_content=content,
                timestamp=timestamp,
            )
        except (json.JSONDecodeError, TypeError):
            # Unstructured text — treat as progress update
            return ChannelEvent(
                event_type="progress",
                details=content[:500],
                raw_content=content,
                timestamp=timestamp,
            )

    # ── LLM Event Judgment ───────────────────────────────────────────────

    async def _judge_event(self, event: ChannelEvent) -> SupervisorAction:
        """Use LLM to judge an event and decide on action."""

        # Fast paths — no LLM needed
        if event.event_type == "completed":
            return SupervisorAction(action="continue")

        if event.event_type == "progress":
            return SupervisorAction(action="continue")

        if event.event_type == "files_changed":
            return SupervisorAction(action="continue")

        if event.event_type == "test_result":
            if event.error or "fail" in event.details.lower():
                self._consecutive_test_failures += 1
                if self._consecutive_test_failures >= self._max_auto_retries:
                    return SupervisorAction(
                        action="notify_user",
                        message=f"테스트가 {self._consecutive_test_failures}회 연속 실패했습니다: {event.details}",
                    )
                return SupervisorAction(
                    action="reply",
                    message=f"테스트 실패를 확인했습니다. 오류를 분석하고 수정해주세요. 실패 내용: {event.details}",
                )
            else:
                self._consecutive_test_failures = 0
                return SupervisorAction(action="continue")

        # Complex events — use LLM
        if self._provider and event.event_type in ("approval_needed", "direction_check", "error"):
            return await self._llm_judge(event)

        # Fallback: approval_needed without LLM → notify user
        if event.event_type == "approval_needed":
            return SupervisorAction(
                action="notify_user",
                message=f"승인 필요: {event.details}",
            )

        return SupervisorAction(action="continue")

    async def _llm_judge(self, event: ChannelEvent) -> SupervisorAction:
        """Use the LLM provider to make a judgment call."""
        from breadmind.llm.base import LLMMessage

        recent_events = self._events[-5:] if len(self._events) > 5 else self._events
        events_summary = "\n".join(
            f"- [{e.event_type}] {e.details[:100]}" for e in recent_events
        )

        messages = [
            LLMMessage(
                role="system",
                content=(
                    "You are a coding task supervisor. Decide how to handle an event from a coding agent. "
                    "Respond with ONLY a JSON object: "
                    '{"action": "continue"|"reply"|"notify_user"|"abort", "message": "..."}\n'
                    "- continue: event is fine, no intervention needed\n"
                    "- reply: send a message back to the coding agent with instructions\n"
                    "- notify_user: escalate to the human user\n"
                    "- abort: stop the coding session"
                ),
            ),
            LLMMessage(
                role="user",
                content=(
                    f"Original task: {self._original_prompt[:500]}\n\n"
                    f"Recent progress:\n{events_summary}\n\n"
                    f"Current event ({event.event_type}): {event.details}\n"
                    f"Error: {event.error or 'none'}\n\n"
                    "What should we do?"
                ),
            ),
        ]

        try:
            response = await self._provider.chat(messages=messages, think_budget=1024)
            data = json.loads(response.content)
            return SupervisorAction(
                action=data.get("action", "continue"),
                message=data.get("message", ""),
            )
        except Exception as e:
            logger.warning("LLM judgment failed: %s", e)
            # Safe fallback
            if event.event_type == "approval_needed":
                return SupervisorAction(action="notify_user", message=event.details)
            return SupervisorAction(action="continue")

    # ── Reply ────────────────────────────────────────────────────────────

    async def send_reply(self, message: str) -> bool:
        """Send a reply to Claude Code through the channel server."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"http://127.0.0.1:{self._channel_port}/reply",
                    json={"message": message, "session_id": self._session_id},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.warning("Failed to send reply: %s", e)
            return False

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def stop(self) -> SessionReport:
        """Stop the supervisor and return the final report."""
        self._running = False
        duration = time.monotonic() - self._start_time

        # Kill channel server
        if self._channel_process and self._channel_process.returncode is None:
            try:
                self._channel_process.kill()
                await self._channel_process.wait()
            except ProcessLookupError:
                pass

        # Stop HTTP server
        if self._http_runner:
            await self._http_runner.cleanup()

        # Build report
        report = SessionReport(
            session_id=self._session_id,
            project=self._project,
            original_prompt=self._original_prompt,
            events=self._events,
            total_files_changed=list(set(self._report_files)),
            duration_seconds=duration,
            success=any(e.event_type == "completed" for e in self._events),
        )

        # Generate summary
        report.summary = self._build_summary(report)

        logger.info(
            "ChannelSupervisor stopped: session=%s events=%d duration=%.1fs",
            self._session_id, len(self._events), duration,
        )

        return report

    def _build_summary(self, report: SessionReport) -> str:
        """Build a human-readable summary from accumulated events."""
        lines = []

        if report.success:
            lines.append(f"[claude] 작업 완료 ({report.duration_seconds:.1f}초)")
        else:
            lines.append(f"[claude] 작업 종료 ({report.duration_seconds:.1f}초)")

        if report.total_files_changed:
            lines.append(f"변경된 파일: {', '.join(report.total_files_changed[:20])}")
            if len(report.total_files_changed) > 20:
                lines.append(f"  ... 외 {len(report.total_files_changed) - 20}개")

        # Summarize test results
        test_events = [e for e in report.events if e.event_type == "test_result"]
        if test_events:
            last_test = test_events[-1]
            lines.append(f"테스트: {last_test.details[:200]}")

        # Include completion details
        completed = [e for e in report.events if e.event_type == "completed"]
        if completed:
            lines.append(f"요약: {completed[-1].details[:500]}")

        # Errors
        errors = [e for e in report.events if e.event_type == "error"]
        if errors:
            lines.append(f"오류 {len(errors)}건:")
            for err in errors[-3:]:
                lines.append(f"  - {err.details[:200]}")

        return "\n".join(lines)

    @property
    def is_running(self) -> bool:
        return self._running

    def get_mcp_config_entry(self) -> dict:
        """Return .mcp.json entry for the channel server."""
        runtime, script = self._resolve_runtime()
        return {
            "command": runtime or "node",
            "args": [str(script or CHANNEL_SERVER_DIR / "channel.ts")],
            "env": {
                "BREADMIND_SUPERVISOR_PORT": str(self._supervisor_port),
                "CHANNEL_PORT": str(self._channel_port),
                "SESSION_ID": self._session_id,
            },
        }
