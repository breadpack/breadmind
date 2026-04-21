"""E2E facades for the Slack-KB test harness.

Split out of ``query_pipeline.py`` in P5 (Task 22+) to keep the production
pipeline module under the 500-line soft cap and because the facade surface
now carries enough test-only logic (real ACL enforcement, sensitive-category
blocking with HR exception, LLM fallback routing) that inlining it obscures
the production orchestrator.

``QueryPipeline.build_for_e2e`` remains the public entry-point; this module
is an implementation detail imported lazily from
``query_pipeline._add_e2e_pipeline_builder``.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from breadmind.llm.base import LLMResponse, TokenUsage
from breadmind.llm.router import AllProvidersFailed
from breadmind.messenger.router import IncomingMessage, OutgoingMessage

if TYPE_CHECKING:
    from breadmind.kb.query_pipeline import QueryPipeline

logger = logging.getLogger(__name__)


# ─── Redactor sync shim ────────────────────────────────────────────────────


class _RedactorSyncAdapter:
    """Sync shim mirroring the 3 calls ``QueryPipeline.answer`` makes on its
    redactor collaborator:

    * ``redact(text) -> (masked, restore_map)``
    * ``abort_if_secrets(masked) -> None`` (raises on hard-block)
    * ``restore(text, restore_map) -> str``

    The production :class:`Redactor` exposes the first two as async + takes
    a ``session_id``. The E2E queries contain no PII we care to un-mask, so
    the round-trip is a no-op on the way out.
    """

    def __init__(self, _unused: Any = None) -> None:
        pass

    def redact(self, text: str):
        from breadmind.kb.redactor import Redactor
        masked = Redactor.default().redact_prompt(text)
        return masked, ""

    def abort_if_secrets(self, text: str) -> None:
        import re as _re
        from breadmind.kb.redactor import (
            _API_KEY_PATTERNS,
            _CC_RE,
            _SSN_RE,
            SecretDetected,
            _luhn_ok,
            _shannon_entropy,
        )
        for pat in _API_KEY_PATTERNS:
            if pat.search(text):
                raise SecretDetected("api key / token pattern matched")
        for match in _CC_RE.findall(text):
            if _luhn_ok(match):
                raise SecretDetected("credit card number (Luhn)")
        if _SSN_RE.search(text):
            raise SecretDetected("SSN pattern matched")
        for token in _re.findall(r"\S{24,}", text):
            if _shannon_entropy(token) >= 4.5:
                raise SecretDetected("high-entropy token")

    def restore(self, text: str, _restore_map) -> str:
        return text


# ─── Fallback router adapter ────────────────────────────────────────────────


class _FallbackChatRouterAdapter:
    """Bridge between ``FallbackRouter.complete(prompt, hits)`` and the
    ``router.chat([LLMMessage, ...]) -> LLMResponse`` shape ``QueryPipeline``
    consumes.

    Wraps each ``chat`` call into one ``complete`` call, translates the
    returned draft into an :class:`LLMResponse`, and re-raises the router's
    flat ``RuntimeError("all providers failed: ...")`` as
    :class:`AllProvidersFailed` so the pipeline's existing search-only
    fallback branch activates.
    """

    provider_name = "fallback"
    model_name = "fallback"

    def __init__(self, fallback_router, known_ids: list[int]) -> None:
        self._router = fallback_router
        self._known_ids = known_ids

    async def chat(self, messages, tools=None, model=None) -> LLMResponse:
        from breadmind.kb.e2e_factories import _extract_kb_ids

        text = "\n".join((m.content or "") for m in messages)
        prompt_ids = _extract_kb_ids(text)
        ids_to_cite = prompt_ids or self._known_ids

        # Synthesize hits for the StubLLM.complete signature — the stubs
        # only use ``h.id`` to echo IDs in the draft; we cite separately.
        hits = [_StubHit(kid) for kid in ids_to_cite[:2]]

        try:
            draft, _usage = await self._router.complete(text, hits)
        except RuntimeError as exc:
            if "all providers failed" in str(exc):
                raise AllProvidersFailed(str(exc)) from exc
            raise

        payload = getattr(draft, "text", str(draft))
        if ids_to_cite:
            tags = " ".join(f"[#{kid}]" for kid in ids_to_cite[:2])
            payload = f"{payload} {tags}".strip()
        return LLMResponse(
            content=payload,
            tool_calls=[],
            usage=TokenUsage(input_tokens=50, output_tokens=25),
            stop_reason="end",
        )


class _StubHit:
    __slots__ = ("id",)

    def __init__(self, kid: int) -> None:
        self.id = kid


def _is_fallback_router(obj: Any) -> bool:
    # Duck-type rather than import FallbackRouter (test-only fixture).
    return hasattr(obj, "_providers") and hasattr(obj, "complete")


# ─── E2E Pipeline facade ────────────────────────────────────────────────────


_HR_SENSITIVE_CATEGORY = "hr_compensation"


class _E2EPipelineFacade:
    """Slack-messenger façade over :class:`QueryPipeline`.

    Adds three P5 concerns on top of the raw pipeline:

    * ACL enforcement via ``org_channel_map`` + ``org_project_members``:
      resolves the channel's project and blocks non-members with a
      low-confidence "근거 부족" stub — no LLM call.
    * Sensitive-category (HR) blocking with HR-project member exception:
      non-members see the block reply with ``#hr-inquiry`` pointer;
      HR-project members get a direct LLM answer.
    * Fallback-router support via :class:`_FallbackChatRouterAdapter`:
      the facade auto-wraps ``FallbackRouter`` so the pipeline's
      ``AllProvidersFailed`` search-only branch still fires.
    """

    def __init__(
        self,
        *,
        cls: type["QueryPipeline"],
        db,
        redis,
        slack,
        llm,
        force_confidence: str | None,
        project_name: str,
    ) -> None:
        self._cls = cls
        self._db = db
        self._redis = redis
        self._slack = slack
        self._llm = llm
        self._force_confidence = force_confidence
        self._project_name = project_name
        self._pipeline: "QueryPipeline | None" = None
        self._known_ids: list[int] = []

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    async def _ensure_pipeline(self) -> "QueryPipeline":
        if self._pipeline is not None:
            return self._pipeline
        from breadmind.kb import e2e_factories as ef
        from breadmind.kb.citation import CitationEnforcer
        from breadmind.kb.query_cache import QueryCache
        from breadmind.kb.retriever import KBRetriever

        pool = ef.AsyncpgConnectionPool(self._db)
        await ef.ensure_e2e_schema(self._db)
        known_ids = await ef.seed_e2e_knowledge(
            self._db, project_name=self._project_name,
        )
        self._known_ids = known_ids

        embedder = ef.StableEmbedder()
        acl = ef._PassThroughACL()
        retriever = KBRetriever(pool, embedder, acl)

        if _is_fallback_router(self._llm):
            router = _FallbackChatRouterAdapter(self._llm, known_ids=known_ids)
        else:
            router = ef._StubChatRouter(self._llm, known_ids=known_ids)
        citer = CitationEnforcer(router)
        reviewer = ef._ForcedReviewer(self._force_confidence)
        sensitive = ef._NullSensitive()
        cache = QueryCache(self._redis)
        redactor = _RedactorSyncAdapter(None)

        async def _resolver(_uid: str, channel_id: str):
            return await self._resolve_project_id_for_channel(channel_id)

        self._pipeline = self._cls(
            retriever=retriever,
            redactor=redactor,
            llm_router=router,
            citer=citer,
            reviewer=reviewer,
            sensitive=sensitive,
            cache=cache,
            quota=None,
            project_resolver=_resolver,
        )
        return self._pipeline

    async def _resolve_project_id_for_channel(self, channel_id: str):
        """Look up the project that owns ``channel_id``.

        Falls back to the seed project when the channel isn't mapped — the
        existing Task 19 tests rely on queries over unmapped channels still
        resolving to the seeded pilot-alpha project.
        """
        pid = await self._db.fetchval(
            "SELECT project_id FROM org_channel_map WHERE channel_id=$1",
            channel_id,
        )
        if pid is not None:
            return pid
        # Fall back to the configured seed project.
        from breadmind.kb.e2e_factories import resolve_project_id
        return await resolve_project_id(self._db, self._project_name)

    # ------------------------------------------------------------------
    # Per-request entry point
    # ------------------------------------------------------------------

    async def handle_slack_mention(
        self, *, user_id: str, channel_id: str, text: str,
    ) -> OutgoingMessage:
        """Drive the full pipeline and post the OutgoingMessage to Slack.

        Executes the P5 pre-flight checks (sensitive category, ACL) before
        delegating to :meth:`QueryPipeline.answer`. On block, posts a
        canned message directly to the fake Slack client and returns.
        """
        # Ensure schema + pipeline exist so DB lookups below don't race.
        await self._ensure_pipeline()

        sensitive_reply = await self._maybe_sensitive_response(
            user_id=user_id, channel_id=channel_id, text=text,
        )
        if sensitive_reply is not None:
            await self._slack.chat_postMessage(
                channel=sensitive_reply.channel_id, text=sensitive_reply.text,
            )
            return sensitive_reply

        acl_reply = await self._maybe_acl_block(
            user_id=user_id, channel_id=channel_id, text=text,
        )
        if acl_reply is not None:
            await self._slack.chat_postMessage(
                channel=acl_reply.channel_id, text=acl_reply.text,
            )
            return acl_reply

        pipeline = self._pipeline
        assert pipeline is not None  # _ensure_pipeline above
        incoming = IncomingMessage(
            text=text, user_id=user_id, channel_id=channel_id, platform="slack",
        )
        out = await pipeline.answer(incoming)
        await self._slack.chat_postMessage(channel=out.channel_id, text=out.text)
        return out

    # ------------------------------------------------------------------
    # Sensitive handling
    # ------------------------------------------------------------------

    async def _maybe_sensitive_response(
        self, *, user_id: str, channel_id: str, text: str,
    ) -> OutgoingMessage | None:
        """Return a block / HR-member reply, or None to continue normally.

        * Non-HR-member + HR-compensation keyword → block reply with
          ``민감 카테고리`` + ``#hr-inquiry`` pointer. LLM not called.
        * HR-member + HR-compensation keyword → route through the LLM
          with a minimal prompt so the scripted HR answer flows through.
        """
        from breadmind.kb.redactor import Redactor

        category = Redactor.default().check_sensitive(text)
        if category != _HR_SENSITIVE_CATEGORY:
            return None

        if await self._user_is_hr_member(user_id):
            reply_text = await self._hr_member_direct_answer(text)
            return OutgoingMessage(
                text=reply_text, channel_id=channel_id, platform="slack",
            )

        block_text = (
            "민감 카테고리(hr_compensation)로 분류되어 답변이 제한됩니다. "
            "HR 관련 문의는 #hr-inquiry 채널을 이용해 주세요."
        )
        return OutgoingMessage(
            text=block_text, channel_id=channel_id, platform="slack",
        )

    async def _user_is_hr_member(self, user_id: str) -> bool:
        hr_id = await self._db.fetchval(
            "SELECT id FROM org_projects WHERE name='hr'",
        )
        if hr_id is None:
            return False
        row = await self._db.fetchval(
            "SELECT 1 FROM org_project_members "
            "WHERE project_id=$1 AND user_id=$2",
            hr_id, user_id,
        )
        return row is not None

    async def _hr_member_direct_answer(self, text: str) -> str:
        """Call the underlying LLM directly (bypass retrieval + citation).

        The HR-member exception has no shared KB to cite — the production
        intent is that HR tooling feeds its own context. For the E2E path
        we just surface the scripted LLM text so tests can assert on the
        answer content.
        """
        llm = self._llm
        # FallbackRouter / StubLLM both expose .complete(prompt, hits)
        if hasattr(llm, "complete"):
            draft, _usage = await llm.complete(text, [])
            return getattr(draft, "text", str(draft))
        # Fall back to the chat adapter if someone plugs in a raw router.
        from breadmind.llm.base import LLMMessage
        adapter = getattr(self, "_pipeline", None)
        if adapter is not None and hasattr(adapter, "_router"):
            resp = await adapter._router.chat([
                LLMMessage(role="user", content=text),
            ])
            return resp.content or ""
        return ""

    # ------------------------------------------------------------------
    # ACL pre-flight
    # ------------------------------------------------------------------

    async def _maybe_acl_block(
        self, *, user_id: str, channel_id: str, text: str,
    ) -> OutgoingMessage | None:
        """Block cross-project queries before they reach the pipeline.

        Two gates:

        1. Channel maps to a project the user isn't a member of →
           block (the ``can_read_channel`` axis from spec §7.3).
        2. Query text references a different project by name than the
           channel it was sent from → block (the ``user_projects`` axis:
           queries about alpha asked from a beta channel leak nothing
           because retrieval is scoped by channel, but we surface a
           clear "근거 부족" signal instead of silently empty hits).

        Channels without an ``org_channel_map`` row fall through — the
        existing Task 19 tests depend on this path.
        """
        pid = await self._db.fetchval(
            "SELECT project_id FROM org_channel_map WHERE channel_id=$1",
            channel_id,
        )
        if pid is None:
            return None
        is_member = await self._db.fetchval(
            "SELECT 1 FROM org_project_members "
            "WHERE project_id=$1 AND user_id=$2",
            pid, user_id,
        )
        if is_member is None:
            return _low_confidence_msg(channel_id)

        # Cross-project query detection: the query names project A while
        # the channel belongs to project B. We fetch the channel's project
        # name and compare against the query's textual project mention.
        channel_project = await self._db.fetchval(
            "SELECT name FROM org_projects WHERE id=$1", pid,
        )
        mentioned = _mentioned_project(text)
        if mentioned and channel_project and mentioned not in channel_project:
            return _low_confidence_msg(channel_id)
        return None


# ─── Query-text helpers ─────────────────────────────────────────────────────


_PROJECT_TOKENS = {
    "alpha": ("알파", "alpha"),
    "beta": ("베타", "beta"),
}


def _mentioned_project(text: str) -> str | None:
    """Return the project token (``'alpha'`` / ``'beta'``) referenced by
    the query text, or ``None`` if no project name is mentioned.
    """
    lower = text.lower()
    for canonical, tokens in _PROJECT_TOKENS.items():
        for tok in tokens:
            if tok.lower() in lower:
                return canonical
    return None


def _low_confidence_msg(channel_id: str) -> OutgoingMessage:
    return OutgoingMessage(
        text=(
            "근거 부족 — 해당 프로젝트 KB 접근 권한이 없거나 "
            "요청하신 내용을 찾지 못했습니다.\n신뢰도: 🔴"
        ),
        channel_id=channel_id,
        platform="slack",
    )
