"""Job Notifier — sends coding job completion/failure alerts to messengers.

Listens to JobTracker events and pushes notifications to configured
messenger channels (Slack, Discord, Telegram, etc.).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("breadmind.coding.notifier")


class JobNotifier:
    """Sends coding job status notifications to messenger platforms."""

    def __init__(self, message_router: Any = None):
        self._router = message_router

    def start(self) -> None:
        """Register as a JobTracker listener."""
        from breadmind.coding.job_tracker import JobTracker
        tracker = JobTracker.get_instance()
        tracker.add_listener(self._on_event)
        logger.info("JobNotifier registered")

    async def _on_event(self, event_type: str, job: Any) -> None:
        """Handle job events — notify on completion/failure."""
        if not self._router:
            return

        if event_type == "job_completed":
            if job.status.value == "completed":
                msg = self._format_success(job)
            else:
                msg = self._format_failure(job)
            await self._send(msg, job)

        elif event_type == "job_cancelled":
            msg = f"🚫 코딩 작업 취소됨\n프로젝트: {job.project}\n진행률: {job.completed_phases}/{job.total_phases} phases"
            await self._send(msg, job)

    def _format_success(self, job: Any) -> str:
        lines = [
            f"✅ 코딩 작업 완료",
            f"프로젝트: {job.project}",
            f"에이전트: {job.agent}",
            f"소요 시간: {job.duration_seconds:.0f}초",
            f"Phase: {job.completed_phases}/{job.total_phases} 완료",
        ]
        files = []
        for p in job.phases:
            files.extend(p.files_changed)
        if files:
            unique = list(set(files))[:10]
            lines.append(f"변경 파일: {', '.join(unique)}")
            if len(set(files)) > 10:
                lines.append(f"  ... 외 {len(set(files)) - 10}개")
        return "\n".join(lines)

    def _format_failure(self, job: Any) -> str:
        lines = [
            f"❌ 코딩 작업 실패",
            f"프로젝트: {job.project}",
            f"에이전트: {job.agent}",
            f"소요 시간: {job.duration_seconds:.0f}초",
            f"Phase: {job.completed_phases}/{job.total_phases} 완료",
        ]
        failed = [p for p in job.phases if p.status.value == "failed"]
        if failed:
            lines.append(f"실패한 Phase:")
            for p in failed[:3]:
                lines.append(f"  - Phase {p.step}: {p.title}")
        if job.error:
            lines.append(f"오류: {job.error[:200]}")
        return "\n".join(lines)

    async def _send(self, message: str, job: Any) -> None:
        """Send notification to all active messenger gateways."""
        try:
            # Use message_router to broadcast to all connected platforms
            if hasattr(self._router, "broadcast"):
                await self._router.broadcast(message)
            elif hasattr(self._router, "route_message"):
                # Send as system notification
                await self._router.route_message(
                    content=message,
                    source="system",
                    channel="coding-jobs",
                )
            logger.info("Job notification sent for %s", job.job_id)
        except Exception as e:
            logger.debug("Failed to send job notification: %s", e)
