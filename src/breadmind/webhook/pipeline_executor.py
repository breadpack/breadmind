"""Pipeline executor: runs pipeline actions sequentially with failure handling and permission checks."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import monotonic
from typing import Any

from breadmind.webhook.actions.base import ActionHandler, ActionResult
from breadmind.webhook.models import (
    ActionType,
    FailureStrategy,
    PermissionLevel,
    Pipeline,
    PipelineAction,
    PipelineContext,
)

logger = logging.getLogger(__name__)


@dataclass
class ExecutionLog:
    """Tracks the full result of a pipeline execution run."""

    pipeline_id: str
    pipeline_name: str
    success: bool = True
    error: str = ""
    action_results: list[ActionResult] = field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: float = 0


class PipelineExecutor:
    """Executes a :class:`~breadmind.webhook.models.Pipeline` action-by-action.

    Each action is checked for permission before being handed to the
    appropriate :class:`~breadmind.webhook.actions.base.ActionHandler`.
    Failures are handled according to the action's
    :class:`~breadmind.webhook.models.FailureStrategy`.
    """

    def __init__(
        self,
        action_handlers: dict[ActionType, ActionHandler] | None = None,
    ) -> None:
        self._handlers: dict[ActionType, ActionHandler] = action_handlers or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        pipeline: Pipeline,
        ctx: PipelineContext,
        permission_level: PermissionLevel,
    ) -> ExecutionLog:
        """Run *pipeline* and return an :class:`ExecutionLog` with timing info.

        Steps:
        1. Reject disabled pipelines immediately.
        2. For each action: check permission, execute, handle failure.
        3. Return the log populated with start/finish timestamps and
           a computed ``duration_ms``.
        """
        log = ExecutionLog(
            pipeline_id=pipeline.id,
            pipeline_name=pipeline.name,
            started_at=datetime.now(timezone.utc),
        )
        start_mono = monotonic()

        # 1. Guard: pipeline must be enabled.
        if not pipeline.enabled:
            log.success = False
            log.error = f"Pipeline '{pipeline.name}' is disabled"
            self._finalise(log, start_mono)
            return log

        # 2. Execute actions sequentially.
        for action in pipeline.actions:
            # Permission check.
            if not permission_level.can_execute(action.action_type):
                result = ActionResult(
                    success=False,
                    error=f"Permission denied: {permission_level.value!r} cannot execute action type {action.action_type.value!r}",
                )
                log.action_results.append(result)
                log.success = False
                break  # Always stop on permission failure.

            handler = self._handlers.get(action.action_type)
            if handler is None:
                result = ActionResult(
                    success=False,
                    error=f"No handler registered for action type {action.action_type.value!r}",
                )
                log.action_results.append(result)
                log.success = False
                break

            result = await handler.execute(action, ctx)

            if result.success:
                log.action_results.append(result)
            else:
                log.action_results.append(result)
                should_stop = await self._handle_failure(action, ctx, permission_level, log)
                if should_stop:
                    log.success = False
                    break

        # 3. Finalise timing.
        self._finalise(log, start_mono)
        return log

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _handle_failure(
        self,
        action: PipelineAction,
        ctx: PipelineContext,
        permission_level: PermissionLevel,
        log: ExecutionLog,
    ) -> bool:
        """Decide what to do after an action failure.

        Returns:
            ``True``  — the pipeline should stop.
            ``False`` — the pipeline should continue to the next action.
        """
        strategy = action.on_failure

        if strategy is FailureStrategy.STOP:
            return True

        if strategy is FailureStrategy.CONTINUE:
            return False

        if strategy is FailureStrategy.RETRY:
            handler = self._handlers.get(action.action_type)
            if handler is None:
                return True

            for attempt in range(action.max_retries):
                logger.debug(
                    "Retrying action %s (attempt %d/%d)",
                    action.action_type.value,
                    attempt + 1,
                    action.max_retries,
                )
                result = await handler.execute(action, ctx)
                if result.success:
                    # Replace the failed result with the successful retry.
                    log.action_results[-1] = result
                    return False
                # Update the stored result with the latest failure.
                log.action_results[-1] = result

            # All retries exhausted.
            return True

        if strategy is FailureStrategy.FALLBACK:
            logger.warning(
                "FALLBACK strategy for action type %s is not yet implemented; stopping pipeline.",
                action.action_type.value,
            )
            return True

        # Unknown strategy — be safe and stop.
        return True

    @staticmethod
    def _finalise(log: ExecutionLog, start_mono: float) -> None:
        """Stamp *log* with finish time and duration."""
        log.finished_at = datetime.now(timezone.utc)
        log.duration_ms = (monotonic() - start_mono) * 1000
