"""Hybrid memory search combining vector similarity and full-text search.

Uses Reciprocal Rank Fusion (RRF) to merge results from both backends,
giving robust retrieval that combines semantic understanding with exact
keyword matching.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SearchResult:
    """A single search result with combined scoring."""

    content: str
    score: float  # Combined score 0.0–1.0
    source: str  # "vector", "fts", "both"
    metadata: dict = field(default_factory=dict)


class VectorBackend(Protocol):
    """Protocol for vector similarity search."""

    async def search(
        self, query: str, limit: int
    ) -> list[tuple[str, float, dict]]: ...


class FTSBackend(Protocol):
    """Protocol for full-text search."""

    async def search(
        self, query: str, limit: int
    ) -> list[tuple[str, float, dict]]: ...


class HybridSearchEngine:
    """Combines vector similarity and full-text search with reciprocal rank fusion.

    Inspired by OpenClaw's SQLite + vector hybrid approach.
    """

    def __init__(
        self,
        vector_backend: VectorBackend | None = None,
        fts_backend: FTSBackend | None = None,
        vector_weight: float = 0.6,
        fts_weight: float = 0.4,
    ) -> None:
        self._vector = vector_backend
        self._fts = fts_backend
        self._vector_weight = vector_weight
        self._fts_weight = fts_weight

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Run hybrid search combining vector and FTS results.

        Uses Reciprocal Rank Fusion (RRF) for score merging.
        Falls back to whichever backend is available if only one is configured.
        """
        vector_results: list[tuple[str, float, dict]] = []
        fts_results: list[tuple[str, float, dict]] = []

        if self._vector is not None:
            vector_results = await self._vector.search(query, limit)
        if self._fts is not None:
            fts_results = await self._fts.search(query, limit)

        if not vector_results and not fts_results:
            return []

        if vector_results and not fts_results:
            return self._wrap_results(vector_results, "vector", limit)
        if fts_results and not vector_results:
            return self._wrap_results(fts_results, "fts", limit)

        return self._reciprocal_rank_fusion(
            vector_results, fts_results, k=60
        )[:limit]

    def _reciprocal_rank_fusion(
        self,
        vector_results: list[tuple[str, float, dict]],
        fts_results: list[tuple[str, float, dict]],
        k: int = 60,
    ) -> list[SearchResult]:
        """Merge results using RRF: ``score = sum(weight_i / (k + rank_i))``."""
        # content -> (accumulated_score, metadata, sources)
        scores: dict[str, float] = defaultdict(float)
        metadata_map: dict[str, dict] = {}
        sources: dict[str, set[str]] = defaultdict(set)

        for rank, (content, _sim, meta) in enumerate(vector_results, start=1):
            scores[content] += self._vector_weight / (k + rank)
            metadata_map.setdefault(content, meta)
            sources[content].add("vector")

        for rank, (content, _sim, meta) in enumerate(fts_results, start=1):
            scores[content] += self._fts_weight / (k + rank)
            metadata_map.setdefault(content, meta)
            sources[content].add("fts")

        # Normalise scores to 0-1 range
        max_score = max(scores.values()) if scores else 1.0
        if max_score == 0:
            max_score = 1.0

        results: list[SearchResult] = []
        for content, raw_score in sorted(
            scores.items(), key=lambda x: x[1], reverse=True
        ):
            src_set = sources[content]
            source = "both" if len(src_set) > 1 else next(iter(src_set))
            results.append(
                SearchResult(
                    content=content,
                    score=raw_score / max_score,
                    source=source,
                    metadata=metadata_map.get(content, {}),
                )
            )

        return results

    async def search_vector_only(
        self, query: str, limit: int = 10
    ) -> list[SearchResult]:
        """Search using only the vector backend."""
        if self._vector is None:
            return []
        results = await self._vector.search(query, limit)
        return self._wrap_results(results, "vector", limit)

    async def search_fts_only(
        self, query: str, limit: int = 10
    ) -> list[SearchResult]:
        """Search using only the FTS backend."""
        if self._fts is None:
            return []
        results = await self._fts.search(query, limit)
        return self._wrap_results(results, "fts", limit)

    @staticmethod
    def _wrap_results(
        raw: list[tuple[str, float, dict]], source: str, limit: int
    ) -> list[SearchResult]:
        return [
            SearchResult(content=c, score=s, source=source, metadata=m)
            for c, s, m in raw[:limit]
        ]


class SimpleTextFTS:
    """Simple in-memory full-text search for when no FTS backend is configured.

    Uses basic tokenization and TF-IDF-like scoring.
    """

    def __init__(self) -> None:
        self._documents: list[tuple[str, dict]] = []

    def index(self, content: str, metadata: dict | None = None) -> None:
        """Add a document to the index."""
        self._documents.append((content, metadata or {}))

    async def search(
        self, query: str, limit: int = 10
    ) -> list[tuple[str, float, dict]]:
        """Search indexed documents using TF-IDF-like scoring."""
        query_tokens = self._tokenize(query)
        if not query_tokens or not self._documents:
            return []

        # Document frequency for IDF
        doc_count = len(self._documents)
        df: dict[str, int] = defaultdict(int)
        doc_token_sets: list[set[str]] = []
        doc_token_lists: list[list[str]] = []

        for content, _ in self._documents:
            tokens = self._tokenize(content)
            doc_token_lists.append(tokens)
            token_set = set(tokens)
            doc_token_sets.append(token_set)
            for t in token_set:
                df[t] += 1

        results: list[tuple[str, float, dict]] = []

        for idx, (content, meta) in enumerate(self._documents):
            tokens = doc_token_lists[idx]
            if not tokens:
                continue

            score = 0.0
            for qt in query_tokens:
                if df.get(qt, 0) == 0:
                    continue
                tf = tokens.count(qt) / len(tokens)
                idf = math.log(1 + doc_count / df[qt])
                score += tf * idf

            if score > 0:
                results.append((content, score, meta))

        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)

        # Normalise scores to 0-1
        if results:
            max_score = results[0][1]
            if max_score > 0:
                results = [
                    (c, s / max_score, m) for c, s, m in results
                ]

        return results[:limit]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Lowercase tokenization with basic punctuation removal."""
        return re.findall(r"[a-z0-9]+", text.lower())
