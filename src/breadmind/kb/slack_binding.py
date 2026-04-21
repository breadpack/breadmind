# src/breadmind/kb/slack_binding.py
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from breadmind.kb.audit import audit_log as _real_audit_log
from breadmind.kb.query_pipeline import QueryPipeline
from breadmind.messenger.router import IncomingMessage

logger = logging.getLogger(__name__)


async def audit_log(**kwargs) -> None:
    """Module-level shim over the real audit_log.

    Tests monkeypatch ``breadmind.kb.slack_binding.audit_log`` to capture
    calls without a live DB. The real ``_real_audit_log`` requires a ``db``
    pool as its first positional argument; that dependency will be satisfied
    during app startup (P3+ wiring phase).
    """
    # No-op by default — production wiring replaces this at startup.
    _ = _real_audit_log  # keep import reachable for linters


def build_slack_query_handler(
    pipeline: QueryPipeline,
) -> Callable[[IncomingMessage], Awaitable[str | None]]:
    """Adapt `QueryPipeline.answer` to the messenger on_message callback
    signature `(IncomingMessage) -> str | None`."""

    async def handler(inc: IncomingMessage) -> str | None:
        if inc.is_approval:
            return None
        try:
            outgoing = await pipeline.answer(inc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("QueryPipeline failed: %s", exc)
            return "내부 오류로 답변하지 못했습니다. 잠시 후 다시 시도해주세요."
        return outgoing.text

    return handler


def build_slack_feedback_handler() -> Callable[[str, str, str], Awaitable[None]]:
    """Return a coroutine that logs KB feedback button clicks to the audit log."""

    async def handler(kind: str, answer_id: str, user_id: str) -> None:
        await audit_log(
            actor=user_id,
            action=f"feedback_{kind}",
            subject_type="kb_answer",
            subject_id=answer_id,
        )

    return handler
