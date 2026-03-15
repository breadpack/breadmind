from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Text embedding service with graceful degradation."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model: Any = None
        self._available: bool | None = None  # None = not checked yet
        self._cache: dict[str, list[float]] = {}
        self._max_cache = 500

    def is_available(self) -> bool:
        if self._available is None:
            try:
                import sentence_transformers  # noqa: F401
                self._available = True
            except ImportError:
                self._available = False
                logger.info("sentence-transformers not installed, embeddings disabled")
        return self._available

    def _load_model(self) -> None:
        if self._model is not None:
            return
        if not self.is_available():
            return
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
            logger.info(f"Loaded embedding model: {self._model_name}")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            self._available = False

    def _cache_key(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    async def encode(self, text: str) -> list[float] | None:
        if not self.is_available():
            return None

        key = self._cache_key(text)
        if key in self._cache:
            return self._cache[key]

        def _encode_sync():
            self._load_model()
            if self._model is None:
                return None
            embedding = self._model.encode(text, show_progress_bar=False)
            return embedding.tolist()

        result = await asyncio.to_thread(_encode_sync)
        if result is not None:
            if len(self._cache) >= self._max_cache:
                # Evict oldest entry
                oldest = next(iter(self._cache))
                del self._cache[oldest]
            self._cache[key] = result
        return result

    async def encode_batch(self, texts: list[str]) -> list[list[float] | None]:
        if not self.is_available():
            return [None] * len(texts)

        results: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        for i, text in enumerate(texts):
            key = self._cache_key(text)
            if key in self._cache:
                results[i] = self._cache[key]
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        if uncached_texts:
            def _encode_batch_sync():
                self._load_model()
                if self._model is None:
                    return None
                embeddings = self._model.encode(uncached_texts, show_progress_bar=False)
                return [e.tolist() for e in embeddings]

            batch_results = await asyncio.to_thread(_encode_batch_sync)
            if batch_results:
                for idx, embedding in zip(uncached_indices, batch_results):
                    results[idx] = embedding
                    key = self._cache_key(uncached_texts[uncached_indices.index(idx)])
                    if len(self._cache) < self._max_cache:
                        self._cache[key] = embedding

        return results

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        if len(a) != len(b) or not a:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
