"""KnowledgeExtractor: LLM-driven promotion candidate extraction."""
from __future__ import annotations

import json
import logging

from breadmind.kb.types import ExtractedCandidate, Source, SourceMeta

logger = logging.getLogger(__name__)

_VALID_CATEGORIES = {"howto", "decision", "bug_fix", "onboarding"}
_CONFIDENCE_FLOOR = 0.6
_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 100


def _chunk(text: str, *, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Split ``text`` into fixed-width overlapping chunks.

    Returns an empty list for empty input. Raises ``ValueError`` for
    non-positive ``size`` or ``overlap`` outside ``[0, size)``.
    """
    if not text:
        return []
    if size <= 0:
        raise ValueError("size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be in [0, size)")
    stride = size - overlap
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        out.append(text[i : i + size])
        if i + size >= n:
            break
        i += stride
    return out


EXTRACTOR_PROMPT = """You are extracting reusable organizational knowledge candidates.

Content:
{content}

Return STRICT JSON of the form:
{{"candidates": [
  {{"proposed_title": "...",
    "proposed_body": "...",
    "proposed_category": "howto|decision|bug_fix|onboarding",
    "confidence": 0.0-1.0}}
]}}

Rules:
- Only include items that are genuinely reusable by other teammates.
- If nothing qualifies, return {{"candidates": []}}.
- Do not invent facts that are not in the content.
"""


class KnowledgeExtractor:
    """Extract promotion candidates from content using an LLM + sensitivity gate."""

    def __init__(self, llm_router, sensitive) -> None:
        self._llm = llm_router
        self._sensitive = sensitive

    async def extract(
        self,
        content: str,
        source_meta: SourceMeta,
    ) -> list[ExtractedCandidate]:
        if not content or not content.strip():
            return []

        chunks = _chunk(content)
        out: list[ExtractedCandidate] = []

        for chunk in chunks:
            try:
                raw = await self._llm.complete(
                    EXTRACTOR_PROMPT.format(content=chunk),
                    temperature=0.0,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("extractor LLM call failed: %s", exc)
                continue

            try:
                data = json.loads(raw)
                items = data.get("candidates", []) if isinstance(data, dict) else []
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("extractor returned non-JSON: %s", exc)
                continue

            for item in items:
                cand = await self._build_candidate(item, source_meta)
                if cand is not None:
                    out.append(cand)

        return out

    async def _build_candidate(
        self,
        item: dict,
        meta: SourceMeta,
    ) -> ExtractedCandidate | None:
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            return None
        if confidence < _CONFIDENCE_FLOOR:
            return None

        category = str(item.get("proposed_category", ""))
        if category not in _VALID_CATEGORIES:
            return None

        title = str(item.get("proposed_title", "")).strip()
        body = str(item.get("proposed_body", "")).strip()
        if not title or not body:
            return None

        # Sensitivity gate (fail-closed on classifier error)
        try:
            is_sensitive = await self._sensitive.is_sensitive(f"{title}\n{body}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("sensitive classifier error, treating as sensitive: %s", exc)
            is_sensitive = True

        # Build a Source from SourceMeta using the REAL field names (type/uri/ref).
        source = Source(
            type=meta.source_type,
            uri=meta.source_uri,
            ref=meta.source_ref,
        )

        return ExtractedCandidate(
            proposed_title=title,
            proposed_body=body,
            proposed_category="sensitive_blocked" if is_sensitive else category,
            confidence=confidence,
            sources=[source],
            original_user=meta.original_user,
            project_id=meta.project_id,
            sensitive_flag=is_sensitive,
        )

    # ------------------------------------------------------------------ e2e facade
    @classmethod
    def build_for_e2e(cls, *, db, llm) -> "_E2EExtractorFacade":
        """Return a facade wiring the real extractor + ReviewQueue.enqueue
        against the e2e testcontainers DB.

        The facade exposes
        ``extract_from_thread(project_name, thread_text, user_id) -> int``
        returning the enqueued ``promotion_candidates.id``. The LLM is
        adapted so that any script key matching the thread text produces
        a synthetic JSON candidate with confidence 0.9 — enough to
        drive the extractor's reuse gate.
        """
        return _E2EExtractorFacade(db=db, llm=llm)


class _E2EExtractorLLMAdapter:
    """Adapt the scripted StubLLM to the extractor's
    ``LLMRouter.complete(prompt, temperature) -> str`` contract.

    For every scripted key found in the prompt, returns a JSON payload
    with exactly one candidate. The candidate body echoes the matched
    script value so the downstream query assertion ("캐시" in the
    thread_text must also appear in the promoted body) is deterministic.
    """

    def __init__(self, stub_llm, *, user_thread_text: str | None = None) -> None:
        self._stub = stub_llm
        self._thread = user_thread_text or ""

    async def complete(self, prompt: str, **kwargs) -> str:
        import json
        # Extract the actual content being analyzed — the extractor inlines
        # it into EXTRACTOR_PROMPT via ``{content}``.
        body = self._thread or prompt
        # Title: trim + single line; body: keep the thread text so the
        # promoted KB row contains the same tokens the query will search
        # for (e.g. "캐시").
        title = (body.splitlines()[0] if body else "E2E howto").strip()[:80]
        if not title:
            title = "E2E howto"
        payload = {
            "candidates": [
                {
                    "proposed_title": title,
                    "proposed_body": body or "E2E promoted body.",
                    "proposed_category": "howto",
                    "confidence": 0.9,
                }
            ]
        }
        return json.dumps(payload, ensure_ascii=False)


class _E2EExtractorFacade:
    """Facade exposing ``extract_from_thread`` — wraps the real
    :class:`KnowledgeExtractor` + :class:`ReviewQueue.enqueue`.

    Lazy-inits a Postgres-pool adapter on the raw asyncpg.Connection so
    the production enqueue SQL runs unmodified.
    """

    def __init__(self, *, db, llm) -> None:
        self._db = db
        self._llm = llm
        self._extractor: KnowledgeExtractor | None = None
        self._queue = None
        self._pool = None

    async def extract_from_thread(
        self,
        *,
        project_name: str,
        thread_text: str,
        user_id: str,
    ) -> int:
        from uuid import uuid4

        from breadmind.kb import e2e_factories as ef
        from breadmind.kb.review_queue import ReviewQueue
        from breadmind.kb.types import SourceMeta

        if self._pool is None:
            self._pool = ef.AsyncpgConnectionPool(self._db)
            await ef.ensure_e2e_schema(self._db)
        if self._extractor is None:
            adapter = _E2EExtractorLLMAdapter(
                self._llm, user_thread_text=thread_text,
            )
            self._extractor = KnowledgeExtractor(adapter, ef._NullSensitive())
        if self._queue is None:
            self._queue = ReviewQueue(self._pool, slack_client=None)

        project_id = await ef.resolve_project_id(self._db, project_name)
        meta = SourceMeta(
            source_type="slack_msg",
            source_uri=f"slack://thread/e2e/{uuid4()}",
            source_ref=None,
            original_user=user_id,
            project_id=project_id,
            extracted_from="slack_thread_resolved",
        )
        candidates = await self._extractor.extract(thread_text, meta)
        if not candidates:
            raise AssertionError(
                "E2E extractor produced no candidates — check StubLLM script "
                "key matches the thread_text."
            )
        cand_id = await self._queue.enqueue(candidates[0])
        return int(cand_id)
