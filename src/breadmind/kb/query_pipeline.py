# src/breadmind/kb/query_pipeline.py
from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from breadmind.kb import metrics as kb_metrics
from breadmind.kb import tracing as kb_tracing
from breadmind.kb.audit import audit_log as _real_audit_log
from breadmind.kb.types import Confidence, EnforcedAnswer, InsufficientEvidence
from breadmind.llm.base import LLMMessage
from breadmind.llm.router import AllProvidersFailed
from breadmind.messenger.router import IncomingMessage, OutgoingMessage

logger = logging.getLogger(__name__)


@dataclass
class AnswerResult:
    """Simplified response surface for test harnesses / facades.

    Production callers receive an :class:`OutgoingMessage`; the
    :meth:`QueryPipeline.build_for_tests` facade wraps responses in this
    dataclass so tests can assert on ``confidence`` without parsing the
    formatted text.
    """

    text: str
    confidence: str
    outgoing: OutgoingMessage

ProjectResolver = Callable[[str, str], Awaitable[Any]]
# (user_id, channel_id) -> project_id (UUID or opaque test label)


async def audit_log(**kwargs) -> None:
    """Module-level shim over the real audit_log.

    Tests monkeypatch ``breadmind.kb.query_pipeline.audit_log`` to capture
    calls without a live DB. In production this shim is a no-op until a
    db-bound version is injected (planned for P3 wiring phase). The real
    ``_real_audit_log`` requires a ``db`` pool as its first positional
    argument; that dependency will be satisfied during app startup.
    """
    # No-op by default — production wiring replaces this at startup.
    _ = _real_audit_log  # keep import reachable for linters


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
        # Metric labels captured in `finally` — initialise to a defensive
        # baseline so every exit path (including early returns and raised
        # exceptions) records a sample with well-defined labels.
        pid_label = "unknown"
        status = "ok"
        confidence_label = "low"
        try:
            category = self._sensitive.classify(incoming.text)
            if category is not None:
                logger.info("blocked sensitive category=%s user=%s", category,
                            incoming.user_id)
                try:
                    kb_metrics.observe_block_sensitive(category=str(category))
                except Exception:  # pragma: no cover — metrics must never break prod
                    logger.exception("observe_block_sensitive failed")
                status = "blocked"
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
            pid_label = pid_str or "unknown"

            cached = await self._cache.get(
                incoming.text, incoming.user_id, pid_str,
            )
            if cached is not None:
                confidence_label = "high"
                return OutgoingMessage(
                    text=cached, channel_id=incoming.channel_id,
                    platform=incoming.platform,
                )

            async with kb_tracing.span_retrieve(
                project=pid_label, query=incoming.text,
            ):
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
                status = "quota_exceeded"
                return OutgoingMessage(
                    text=self._format_search_only(hits),
                    channel_id=incoming.channel_id,
                    platform=incoming.platform,
                )

            async with kb_tracing.span_redact(pattern_count=0):
                masked_query, restore_map = self._redactor.redact(incoming.text)
                try:
                    self._redactor.abort_if_secrets(masked_query)
                except Exception as exc:  # redactor raises SecretDetected
                    logger.info("redactor aborted (secret detected): %s", exc)
                    status = "secret_blocked"
                    return OutgoingMessage(
                        text=(
                            "질의에 비밀값이 포함되어 있습니다. "
                            "제거 후 재시도 해주세요."
                        ),
                        channel_id=incoming.channel_id,
                        platform=incoming.platform,
                    )

            snippets = "\n".join(
                f"[#{h.knowledge_id}] {h.title}: {h.body[:400]}" for h in hits
            )
            system = (
                "Answer using ONLY the KB snippets below. Cite every factual "
                "sentence with [#<id>] referencing only provided IDs."
            )
            user = f"KB:\n{snippets}\n\nQuestion: {masked_query}"
            llm_provider = getattr(self._router, "provider_name", "unknown")
            llm_model = getattr(self._router, "model_name", "unknown")
            try:
                async with kb_tracing.span_llm_call(
                    provider=llm_provider, model=llm_model,
                ):
                    with kb_metrics.time_llm(
                        provider=llm_provider, model=llm_model,
                    ):
                        resp = await self._router.chat([
                            LLMMessage(role="system", content=system),
                            LLMMessage(role="user", content=user),
                        ])
                try:
                    kb_metrics.observe_llm_tokens(
                        provider=llm_provider, direction="input",
                        n=int(getattr(resp.usage, "input_tokens", 0) or 0),
                    )
                    kb_metrics.observe_llm_tokens(
                        provider=llm_provider, direction="output",
                        n=int(getattr(resp.usage, "output_tokens", 0) or 0),
                    )
                except Exception:  # pragma: no cover — defensive
                    logger.exception("observe_llm_tokens failed")
                if self._quota is not None:
                    await self._quota.charge(
                        incoming.user_id,
                        resp.usage.input_tokens + resp.usage.output_tokens,
                    )
            except AllProvidersFailed:
                logger.warning("All LLM providers failed — search-only response")
                status = "llm_failed"
                return OutgoingMessage(
                    text="AI 답변 불가(모든 provider 실패), 검색만 모드:\n" +
                         self._format_search_only(hits),
                    channel_id=incoming.channel_id,
                    platform=incoming.platform,
                )
            draft = resp.content or ""

            try:
                async with kb_tracing.span_cite(count=len(hits)):
                    enforced: EnforcedAnswer = await self._citer.enforce(
                        draft, hits,
                    )
            except InsufficientEvidence:
                logger.info("InsufficientEvidence → Top-3 fallback")
                status = "insufficient_evidence"
                return OutgoingMessage(
                    text="확실한 답변 불가, 관련 근거 제시:\n" +
                         self._format_search_only(hits),
                    channel_id=incoming.channel_id,
                    platform=incoming.platform,
                )
            if self._has_strong_signals(hits):
                confidence = Confidence.HIGH
            else:
                async with kb_tracing.span_self_review(
                    confidence="pending",
                ):
                    confidence = await self._reviewer.score(enforced.text, hits)
            confidence_label = confidence.value
            restored_text = self._redactor.restore(enforced.text, restore_map)

            answer_id = uuid.uuid4().hex[:8]
            formatted = self._format(
                restored_text, enforced, confidence, answer_id,
            )

            await self._cache.set(
                incoming.text, incoming.user_id, pid_str, formatted,
            )

            # NOTE: audit_log(db, ...) requires a real db pool in production; the
            # db dependency will be injected in a later wiring phase (P3+).
            # Tests monkeypatch qp.audit_log so db is not required there.
            await audit_log(
                actor=incoming.user_id,
                action="query",
                subject_type="org_knowledge",
                subject_id=",".join(str(h.knowledge_id) for h in hits),
                project_id=project_id,
                metadata={
                    "confidence": confidence.value,
                    "answer_id": answer_id,
                    "tokens": (
                        resp.usage.input_tokens + resp.usage.output_tokens
                    ),
                },
            )

            return OutgoingMessage(
                text=formatted,
                channel_id=incoming.channel_id,
                platform=incoming.platform,
            )
        except Exception:
            status = "error"
            raise
        finally:
            try:
                kb_metrics.observe_query(
                    project=pid_label,
                    status=status,
                    confidence=confidence_label,
                )
            except Exception:  # pragma: no cover — metrics never break prod
                logger.exception("observe_query failed")

    @staticmethod
    def _has_strong_signals(hits) -> bool:
        """Skip self-review when the retrieval signal is already strong:
        ≥3 hits and the top hit scored ≥ 0.85 (RRF fused)."""
        return len(hits) >= 3 and hits and hits[0].score >= 0.85

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

    # ------------------------------------------------------------------ test facade
    @classmethod
    def build_for_tests(cls) -> "_TestPipeFacade":
        """Return a lightweight facade wired with deterministic stubs.

        The facade exposes ``answer(user_id=..., project_id=...,
        channel_id=..., text=...) -> AnswerResult`` so metric-focused
        tests can drive the pipeline without constructing an
        ``IncomingMessage`` / mocking every collaborator. The underlying
        :class:`QueryPipeline` still runs the production code path, so
        the full span + counter stack is exercised.
        """
        from unittest.mock import AsyncMock, MagicMock

        from breadmind.kb.types import KBHit, Source
        from breadmind.llm.base import LLMResponse, TokenUsage

        hit = KBHit(
            knowledge_id=1, title="stub", body="stub body", score=0.9,
            sources=[Source(type="confluence", uri="https://wiki/1")],
        )

        retriever = MagicMock()
        retriever.search = AsyncMock(return_value=[hit])

        redactor = MagicMock()
        redactor.redact.return_value = ("masked", {})
        redactor.abort_if_secrets.return_value = None
        redactor.restore.side_effect = lambda text, _map: text

        llm_response = LLMResponse(
            content="stub answer [#1]", tool_calls=[],
            usage=TokenUsage(input_tokens=5, output_tokens=7),
            stop_reason="end",
        )
        router = MagicMock()
        router.chat = AsyncMock(return_value=llm_response)
        router.provider_name = "stub"
        router.model_name = "stub-model"

        citer = MagicMock()
        citer.enforce = AsyncMock(
            return_value=EnforcedAnswer(text="stub answer [#1]",
                                        citations=hit.sources),
        )
        reviewer = MagicMock()
        reviewer.score = AsyncMock(return_value=Confidence.HIGH)

        sensitive = MagicMock()
        sensitive.classify.return_value = None

        cache = MagicMock()
        cache.get = AsyncMock(return_value=None)
        cache.set = AsyncMock(return_value=None)

        pipeline = cls(
            retriever=retriever,
            redactor=redactor,
            llm_router=router,
            citer=citer,
            reviewer=reviewer,
            sensitive=sensitive,
            cache=cache,
            quota=None,
            project_resolver=None,
        )
        return _TestPipeFacade(pipeline)


class _TestPipeFacade:
    """Adapter exposing a kwargs-friendly ``answer`` returning AnswerResult."""

    def __init__(self, pipeline: QueryPipeline) -> None:
        self._pipeline = pipeline

    async def answer(
        self,
        *,
        user_id: str,
        project_id: str,
        channel_id: str,
        text: str,
        platform: str = "slack",
    ) -> AnswerResult:
        async def _resolver(_uid: str, _cid: str):
            # Accept either a real UUID string or an opaque project label
            # (the latter is only used by test harnesses — the production
            # resolver always returns a UUID).
            try:
                return UUID(project_id)
            except (ValueError, AttributeError):
                return project_id

        self._pipeline._project_resolver = _resolver
        incoming = IncomingMessage(
            text=text, user_id=user_id, channel_id=channel_id,
            platform=platform,
        )
        out = await self._pipeline.answer(incoming)
        # Recover confidence from the formatted badge — the prod format is
        # stable (`신뢰도: <emoji>`), so we peek at that rather than storing
        # confidence on OutgoingMessage (which is a messenger DTO).
        badge_to_conf = {"🟢": "high", "🟡": "medium", "🔴": "low"}
        confidence = "high"
        for badge, label in badge_to_conf.items():
            if badge in out.text:
                confidence = label
                break
        return AnswerResult(text=out.text, confidence=confidence,
                            outgoing=out)
