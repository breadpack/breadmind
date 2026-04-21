# src/breadmind/kb/slack_binding.py
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from breadmind.kb.query_pipeline import QueryPipeline
from breadmind.messenger.router import IncomingMessage

logger = logging.getLogger(__name__)


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
