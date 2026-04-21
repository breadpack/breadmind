# src/breadmind/kb/query_pipeline.py
from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from uuid import UUID

from breadmind.kb.types import Confidence, EnforcedAnswer, InsufficientEvidence
from breadmind.llm.base import LLMMessage
from breadmind.messenger.router import IncomingMessage, OutgoingMessage

logger = logging.getLogger(__name__)

ProjectResolver = Callable[[str, str], Awaitable[UUID]]
# (user_id, channel_id) -> project_id


class QueryPipeline:
    """Orchestrates: sensitive-check → cache → retriever → redactor → LLM
    → citation → self-review → format → cache-store. Returns OutgoingMessage
    suitable for any MessengerGateway.send()."""

    def __init__(
        self,
        retriever,
        redactor,
        llm_router,
        citer,
        reviewer,
        sensitive,
        cache,
        quota=None,
        project_resolver: ProjectResolver | None = None,
    ) -> None:
        self._retriever = retriever
        self._redactor = redactor
        self._router = llm_router
        self._citer = citer
        self._reviewer = reviewer
        self._sensitive = sensitive
        self._cache = cache
        self._quota = quota
        self._project_resolver = project_resolver

    async def answer(self, incoming: IncomingMessage) -> OutgoingMessage:
        category = self._sensitive.classify(incoming.text)
        if category is not None:
            logger.info("blocked sensitive category=%s user=%s", category,
                        incoming.user_id)
            return OutgoingMessage(
                text=(
                    "이 질의는 민감 카테고리(%s)로 분류되어 답변이 제한됩니다. "
                    "담당자 채널로 문의해주세요." % category
                ),
                channel_id=incoming.channel_id,
                platform=incoming.platform,
            )

        project_id = await self._project_resolver(
            incoming.user_id, incoming.channel_id,
        ) if self._project_resolver else None
        pid_str = str(project_id) if project_id is not None else ""

        cached = await self._cache.get(incoming.text, incoming.user_id, pid_str)
        if cached is not None:
            return OutgoingMessage(
                text=cached, channel_id=incoming.channel_id,
                platform=incoming.platform,
            )

        hits = await self._retriever.search(
            query=incoming.text,
            user_id=incoming.user_id,
            project_id=project_id,
            top_k=5,
        )

        if self._quota is not None and await self._quota.is_exceeded(
            incoming.user_id,
        ):
            logger.info("quota exceeded — search-only for user=%s",
                        incoming.user_id)
            return OutgoingMessage(
                text=self._format_search_only(hits),
                channel_id=incoming.channel_id,
                platform=incoming.platform,
            )

        masked_query, restore_map = self._redactor.redact(incoming.text)
        self._redactor.abort_if_secrets(masked_query)

        snippets = "\n".join(
            f"[#{h.knowledge_id}] {h.title}: {h.body[:400]}" for h in hits
        )
        system = (
            "Answer using ONLY the KB snippets below. Cite every factual "
            "sentence with [#<id>] referencing only provided IDs."
        )
        user = f"KB:\n{snippets}\n\nQuestion: {masked_query}"
        resp = await self._router.chat([
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user),
        ])
        draft = resp.content or ""

        try:
            enforced: EnforcedAnswer = await self._citer.enforce(draft, hits)
        except InsufficientEvidence:
            logger.info("InsufficientEvidence → Top-3 fallback")
            return OutgoingMessage(
                text="확실한 답변 불가, 관련 근거 제시:\n" +
                     self._format_search_only(hits),
                channel_id=incoming.channel_id,
                platform=incoming.platform,
            )
        confidence: Confidence = await self._reviewer.score(enforced.text, hits)
        restored_text = self._redactor.restore(enforced.text, restore_map)

        answer_id = uuid.uuid4().hex[:8]
        formatted = self._format(restored_text, enforced, confidence, answer_id)

        await self._cache.set(
            incoming.text, incoming.user_id, pid_str, formatted,
        )

        return OutgoingMessage(
            text=formatted,
            channel_id=incoming.channel_id,
            platform=incoming.platform,
        )

    @staticmethod
    def _confidence_badge(c: Confidence) -> str:
        return {"high": "🟢", "medium": "🟡", "low": "🔴"}[c.value]

    def _format(
        self,
        body: str,
        enforced: EnforcedAnswer,
        confidence: Confidence,
        answer_id: str,
    ) -> str:
        lines = [body]
        if enforced.citations:
            cites = ", ".join(
                f"<{c.uri}|{c.type}>" for c in enforced.citations
            )
            lines.append(f"📎 출처: {cites}")
        lines.append(f"신뢰도: {self._confidence_badge(confidence)}")
        if confidence is Confidence.LOW:
            lines.append("⚠️ 담당자 확인 권장")
        lines.append(f"answer_id={answer_id}")
        return "\n".join(lines)

    @staticmethod
    def _format_search_only(hits) -> str:
        if not hits:
            return "검색만 모드: 관련 KB 없음."
        lines = ["검색만 모드(일일 토큰 초과) — 관련 KB Top-3:"]
        for h in hits[:3]:
            uri = h.sources[0].uri if h.sources else ""
            lines.append(f"• [#{h.knowledge_id}] {h.title} {uri}".rstrip())
        return "\n".join(lines)
