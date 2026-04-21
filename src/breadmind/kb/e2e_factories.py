"""Shared E2E factory helpers for the Slack-KB test harness.

The ``build_for_e2e`` classmethods on :class:`QueryPipeline`,
:class:`KnowledgeExtractor`, :class:`ReviewQueue`, and
:class:`ConfluenceConnector` all need the same infrastructure glue:

* Adapt a raw ``asyncpg.Connection`` (what the ``tests/e2e/conftest.py``
  ``db`` fixture yields) into something that exposes
  ``async with db.acquire() as conn:`` — production KB code universally
  uses that pool-shaped idiom.
* A deterministic embedder that returns 1024-dim vectors keyed by
  substring so Korean queries hit the rows we seed.
* An LLM ``chat``-router adapter wrapping the scripted ``StubLLM`` from
  ``tests/e2e/fixtures/llm.py`` so the real
  :class:`CitationEnforcer` / :class:`SelfReviewer` code paths run.
* An idempotent schema augmentation step that adds the ``tsv`` column +
  GIN index that production migrations (004) don't install. Plus a
  small seed of KB rows tuned to the three golden queries used by
  ``tests/e2e/test_query_full_path.py``.

These helpers are **test-only**. Keeping them in-tree (not in
``tests/``) lets every production class expose a symmetric
``build_for_e2e`` without cross-package imports.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from breadmind.llm.base import LLMResponse, TokenUsage


_EMBED_DIM = 1024


# ─── DB pool adapter ──────────────────────────────────────────────────────────


class AsyncpgConnectionPool:
    """Wrap a single ``asyncpg.Connection`` as a pool-shaped handle.

    The production KB code uses ``async with db.acquire() as conn:`` uniformly.
    The ``tests/e2e/conftest.py`` fixture yields a raw connection for speed,
    so we adapt it here. The adapter is re-entrant: nested ``acquire()``
    calls simply re-yield the same underlying connection.
    """

    def __init__(self, conn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self._conn

    # Forward the handful of direct methods some connectors call.
    async def fetch(self, *args: Any, **kwargs: Any):
        return await self._conn.fetch(*args, **kwargs)

    async def fetchrow(self, *args: Any, **kwargs: Any):
        return await self._conn.fetchrow(*args, **kwargs)

    async def fetchval(self, *args: Any, **kwargs: Any):
        return await self._conn.fetchval(*args, **kwargs)

    async def execute(self, *args: Any, **kwargs: Any):
        return await self._conn.execute(*args, **kwargs)


# ─── Deterministic embedder ───────────────────────────────────────────────────


class StableEmbedder:
    """1024-d vector derived from substring keywords.

    Queries / bodies sharing any registered keyword receive (mostly) the
    same vector, which makes pgvector cosine similarity high between them
    — high enough to drive the HNSW index into a predictable ordering
    without a real embedding backend.
    """

    _KEYWORDS: tuple[tuple[str, int], ...] = (
        ("결제", 1),
        ("메모리 누수", 1),
        ("memory leak", 1),
        ("CL 12345", 1),
        ("CI 파이프라인", 2),
        ("CI pipeline", 2),
        ("클라 빌드", 3),
        ("빌드 실패", 3),
        ("캐시", 3),
    )

    async def encode(self, text: str) -> list[float]:
        # Start from a text-specific base (via sha) so unrelated queries
        # stay apart in embedding space.
        h = hashlib.sha256(text.encode("utf-8")).digest()
        base = [((h[i % len(h)] / 255.0) - 0.5) * 0.1 for i in range(_EMBED_DIM)]
        for kw, slot in self._KEYWORDS:
            if kw in text:
                # Bias a narrow band strongly — makes cosine-similar vectors
                # when two texts share the same keyword (= slot).
                start = slot * 10
                for i in range(start, start + 30):
                    base[i % _EMBED_DIM] = 1.0
        return base


# ─── LLM chat adapter (wraps StubLLM) ─────────────────────────────────────────


class _StubChatRouter:
    """Adapt the ``StubLLM`` fixture to the ``.chat([LLMMessage])`` interface
    :class:`QueryPipeline` uses. Every response automatically appends
    ``[#<id>]`` tokens for each provided KBHit so the real
    :class:`CitationEnforcer` validates on the first pass.
    """

    provider_name = "stub-e2e"
    model_name = "stub-e2e-model"

    def __init__(self, stub_llm, known_ids: list[int]) -> None:
        self._stub = stub_llm
        # IDs to embed into the answer as [#id] so CitationEnforcer passes.
        self._known_ids = known_ids

    async def chat(self, messages, tools=None, model=None) -> LLMResponse:
        # Flatten the message content so we can match the StubLLM.script keys.
        text = "\n".join((m.content or "") for m in messages)
        # Script match — StubLLM does a substring match against prompt.
        payload: str | None = None
        for key, answer in self._stub.script.items():
            if key in text:
                payload = answer
                break
        # Fallback: echo a short snippet from the KB context block so the
        # downstream assertion can find substrings that appear in the
        # retrieved body (e.g. the promotion E2E test which queries for a
        # term from the approved knowledge body, with no script match).
        if payload is None:
            snippet = _extract_kb_snippet(text)
            payload = snippet or "근거 부족"
        # Prefer citation IDs actually present in the prompt (they come
        # straight from the retrieved hits for THIS call) over the seed
        # IDs captured at construction time. If the second pass is a
        # regeneration retry from CitationEnforcer, the retry prompt also
        # carries the allowed IDs, so this path stays correct.
        prompt_ids = _extract_kb_ids(text)
        ids_to_cite = prompt_ids or self._known_ids
        if ids_to_cite:
            tags = " ".join(f"[#{kid}]" for kid in ids_to_cite[:2])
            payload = f"{payload} {tags}".strip()
        return LLMResponse(
            content=payload, tool_calls=[],
            usage=TokenUsage(input_tokens=50, output_tokens=25),
            stop_reason="end",
        )


def _extract_kb_snippet(prompt_text: str) -> str | None:
    """Pull the first non-empty KB body from a pipeline user-prompt.

    The pipeline formats retrieved hits as ``[#<id>] <title>: <body>`` —
    we grab the body of the first such line so the LLM stub can echo it.
    Used only by ``_StubChatRouter`` when no script key matches.
    """
    import re
    for line in prompt_text.splitlines():
        m = re.match(r"^\[#\d+\]\s*[^:]+:\s*(.+)$", line)
        if m:
            return m.group(1).strip()
    return None


def _extract_kb_ids(prompt_text: str) -> list[int]:
    """Return the ``[#id]`` integers in the order they appear in a prompt.

    The pipeline inlines retrieved hits as ``[#<id>] <title>: <body>``
    and the CitationEnforcer regen prompt re-lists them the same way;
    either prompt shape yields the IDs the stub answer is allowed to
    cite.
    """
    import re
    return [int(m.group(1)) for m in re.finditer(r"\[#(\d+)\]", prompt_text)]


# ─── Fixed SelfReviewer ───────────────────────────────────────────────────────


class _ForcedReviewer:
    """Override SelfReviewer to return a caller-chosen Confidence.

    Lets the E2E tests force a deterministic medium / low outcome without
    trying to shape retrieval or draft text to naturally trip the adversarial
    review LLM. When ``force`` is ``None`` the reviewer returns HIGH.
    """

    def __init__(self, force: str | None) -> None:
        self._force = force

    async def score(self, answer: str, hits) -> Any:
        from breadmind.kb.types import Confidence
        if self._force is None:
            return Confidence.HIGH
        return Confidence(self._force)


# ─── Pass-through ACL ─────────────────────────────────────────────────────────


class _PassThroughACL:
    """ACL that allows every (user, channel) pair — fine for E2E because
    the seeded channels are project_public or the test user is a lead.
    """

    async def filter_knowledge(self, user_id: str, project_id, candidate_ids):
        return list(candidate_ids)

    async def can_read_channel(self, user_id: str, channel_id: str) -> bool:
        return True

    async def user_projects(self, user_id: str):
        return []


# ─── Null sensitive classifier ────────────────────────────────────────────────


class _NullSensitive:
    def classify(self, text: str):
        return None

    async def is_sensitive(self, text: str) -> bool:
        return False


# ─── Schema augmentation + seed ───────────────────────────────────────────────


_TSV_DDL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name='org_knowledge' AND column_name='tsv'
    ) THEN
        ALTER TABLE org_knowledge
            ADD COLUMN tsv tsvector GENERATED ALWAYS AS
            (to_tsvector('simple', title || ' ' || body)) STORED;
    END IF;
END $$;
"""

_TSV_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_org_kn_tsv "
    "ON org_knowledge USING gin(tsv);"
)

# ``ON CONFLICT (name) DO NOTHING`` on ``org_projects`` requires a unique
# index on ``name``. Migration 004 doesn't declare one (see
# ``scripts/seed_pilot_data.py::_upsert_project`` for the production
# workaround); install it here so E2E tests using the idiomatic
# ``ON CONFLICT (name)`` syntax work without touching migrations.
_ORG_PROJECTS_NAME_UQ = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_org_projects_name "
    "ON org_projects(name);"
)


# Rows intentionally keyed to the three test queries in
# tests/e2e/test_query_full_path.py + the promotion + confluence tests.
_SEED_KB_ROWS = [
    {
        "title": "결제 모듈 메모리 누수 postmortem",
        "body": "결제 모듈 메모리 누수는 CL 12345 에서 캐시 eviction 버그 패치로 해결되었다.",
        "category": "bug_fix",
        "source_uri": "https://wiki/payment-leak",
        "source_type": "confluence",
    },
    {
        "title": "CI 파이프라인 확장 가이드",
        "body": "CI 파이프라인은 worker pool 스케일 아웃 + 캐시 공유로 확장한다.",
        "category": "howto",
        "source_uri": "https://wiki/ci-scale",
        "source_type": "confluence",
    },
]


async def ensure_e2e_schema(conn) -> None:
    """Install the ``tsv`` column + GIN index if missing.

    Production migrations (004_org_kb) do not install ``tsv``; KB unit
    tests work around this in their own conftest. Keeping the idempotent
    DDL here so the E2E harness doesn't mutate the migration files.
    """
    await conn.execute(_TSV_DDL)
    await conn.execute(_TSV_INDEX)
    await conn.execute(_ORG_PROJECTS_NAME_UQ)


async def seed_e2e_knowledge(
    conn,
    *,
    project_name: str = "pilot-alpha",
) -> list[int]:
    """Idempotently insert a handful of KB rows tuned to the test queries.

    Returns the inserted / existing ``id`` list in seed order so callers
    can assert on specific rows. Safe to call multiple times; rows are
    keyed on ``(project_id, title)`` and skipped on conflict.
    """
    project_id: UUID = await conn.fetchval(
        "SELECT id FROM org_projects WHERE name=$1", project_name,
    )
    if project_id is None:
        raise RuntimeError(
            f"E2E seed: project {project_name} missing — run seed_pilot_data.py"
        )
    out: list[int] = []
    embedder = StableEmbedder()
    for row in _SEED_KB_ROWS:
        existing = await conn.fetchval(
            "SELECT id FROM org_knowledge WHERE project_id=$1 AND title=$2",
            project_id, row["title"],
        )
        if existing is not None:
            out.append(int(existing))
            continue
        vec = await embedder.encode(f"{row['title']} {row['body']}")
        vec_lit = "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
        kid = await conn.fetchval(
            """
            INSERT INTO org_knowledge
                (project_id, title, body, category, embedding)
            VALUES ($1, $2, $3, $4, $5::vector)
            RETURNING id
            """,
            project_id, row["title"], row["body"], row["category"], vec_lit,
        )
        await conn.execute(
            """
            INSERT INTO kb_sources (knowledge_id, source_type, source_uri)
            VALUES ($1, $2, $3)
            """,
            kid, row["source_type"], row["source_uri"],
        )
        out.append(int(kid))
    return out


async def resolve_project_id(conn, project_name: str) -> UUID:
    pid = await conn.fetchval(
        "SELECT id FROM org_projects WHERE name=$1", project_name,
    )
    if pid is None:
        raise RuntimeError(f"project {project_name} not seeded")
    return pid


# ─── Confluence fixtures loader ────────────────────────────────────────────────


def load_confluence_fixtures(path: str) -> list[dict]:
    """Load the JSON file written by ``scripts/seed_pilot_data.py``.

    The seed writes ``tests/e2e/fixtures/data/confluence_pages.json`` with
    items of shape ``{id, title, space, body}``. The E2E connector facade
    consumes these directly — no HTTP, no retries, no auth.
    """
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
