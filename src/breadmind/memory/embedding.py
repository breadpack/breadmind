from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Text embedding service with provider API support and graceful degradation.

    Priority: 1) Provider API (Gemini/OpenAI) 2) Local model (fastembed/sentence-transformers) 3) None
    """

    def __init__(
        self,
        provider: str = "auto",  # "gemini", "openai", "ollama", "local", "auto"
        api_key: str = "",
        model_name: str = "",
        ollama_base_url: str = "http://localhost:11434",
    ):
        self._provider = provider
        self._api_key = api_key
        self._model_name = model_name
        self._ollama_base_url = ollama_base_url
        self._backend: str | None = None  # resolved backend
        self._resolved: bool = False  # True once resolution attempted
        self._local_model: Any = None
        self._cache: dict[str, list[float]] = {}
        self._max_cache = 500
        self._dimensions: int = 384  # updated when backend resolves

    def is_available(self) -> bool:
        if self._resolved:
            return self._backend is not None
        self._resolve_backend()
        return self._backend is not None

    def _resolve_backend(self) -> None:
        """Resolve which embedding backend to use."""
        if self._resolved:
            return
        self._resolved = True

        if self._provider in ("gemini", "auto") and self._api_key:
            try:
                import aiohttp  # noqa: F401
                self._backend = "gemini"
                self._model_name = self._model_name or "gemini-embedding-001"
                self._dimensions = 768
                logger.info(f"Embedding backend: Gemini API ({self._model_name})")
                return
            except ImportError:
                pass

        if self._provider in ("openai", "auto") and self._api_key:
            try:
                import aiohttp  # noqa: F401
                self._backend = "openai"
                self._model_name = self._model_name or "text-embedding-3-small"
                self._dimensions = 1536
                logger.info(f"Embedding backend: OpenAI API ({self._model_name})")
                return
            except ImportError:
                pass

        if self._provider in ("ollama", "auto"):
            try:
                import aiohttp
                # Quick connectivity check before committing to ollama
                import socket
                host = self._ollama_base_url.replace("http://", "").replace("https://", "")
                h, _, p = host.partition(":")
                port = int(p) if p else 11434
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                try:
                    sock.connect((h, port))
                    sock.close()
                except (socket.timeout, ConnectionRefusedError, OSError):
                    sock.close()
                    logger.info("Ollama not reachable, skipping")
                    raise ConnectionError("Ollama not reachable")
                self._backend = "ollama"
                self._model_name = self._model_name or "nomic-embed-text"
                self._dimensions = 768
                logger.info(f"Embedding backend: Ollama ({self._model_name})")
                return
            except (ImportError, ConnectionError):
                pass

        if self._provider in ("local", "auto"):
            try:
                import sentence_transformers  # noqa: F401
                self._backend = "local"
                self._model_name = self._model_name or "all-MiniLM-L6-v2"
                self._dimensions = 384
                logger.info(f"Embedding backend: local ({self._model_name})")
                return
            except ImportError:
                pass

        logger.info("No embedding backend available, embeddings disabled")

    def _cache_key(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    async def encode(self, text: str) -> list[float] | None:
        if not self.is_available():
            return None

        key = self._cache_key(text)
        if key in self._cache:
            return self._cache[key]

        result = None
        try:
            if self._backend == "gemini":
                result = await self._encode_gemini(text)
            elif self._backend == "openai":
                result = await self._encode_openai(text)
            elif self._backend == "ollama":
                result = await self._encode_ollama(text)
            elif self._backend == "local":
                result = await self._encode_local(text)
        except Exception as e:
            logger.warning(f"Embedding encode failed ({self._backend}): {e}")
            return None

        if result is not None:
            if len(self._cache) >= self._max_cache:
                oldest = next(iter(self._cache))
                del self._cache[oldest]
            self._cache[key] = result
        return result

    async def encode_batch(self, texts: list[str]) -> list[list[float] | None]:
        if not self.is_available():
            return [None] * len(texts)

        results: list[list[float] | None] = [None] * len(texts)
        uncached: list[tuple[int, str]] = []

        for i, text in enumerate(texts):
            key = self._cache_key(text)
            if key in self._cache:
                results[i] = self._cache[key]
            else:
                uncached.append((i, text))

        if uncached:
            # Encode uncached items individually (batch API varies by provider)
            for idx, text in uncached:
                embedding = await self.encode(text)
                results[idx] = embedding

        return results

    async def _encode_gemini(self, text: str) -> list[float] | None:
        import aiohttp
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._model_name}:embedContent?key={self._api_key}"
        body = {"model": f"models/{self._model_name}", "content": {"parts": [{"text": text}]}}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.warning(f"Gemini embedding error: {resp.status} {error[:200]}")
                    return None
                data = await resp.json()
                return data.get("embedding", {}).get("values")

    async def _encode_openai(self, text: str) -> list[float] | None:
        import aiohttp
        url = "https://api.openai.com/v1/embeddings"
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        body = {"model": self._model_name, "input": text}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.warning(f"OpenAI embedding error: {resp.status} {error[:200]}")
                    return None
                data = await resp.json()
                return data["data"][0]["embedding"]

    async def _encode_ollama(self, text: str) -> list[float] | None:
        import aiohttp
        url = f"{self._ollama_base_url}/api/embed"
        body = {"model": self._model_name, "input": text}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                embeddings = data.get("embeddings", [])
                return embeddings[0] if embeddings else None

    async def _encode_local(self, text: str) -> list[float] | None:
        def _sync():
            if self._local_model is None:
                from sentence_transformers import SentenceTransformer
                self._local_model = SentenceTransformer(self._model_name)
            return self._local_model.encode(text, show_progress_bar=False).tolist()
        return await asyncio.to_thread(_sync)

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
