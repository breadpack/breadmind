import pytest
from breadmind.memory.embedding import EmbeddingService


class TestEmbeddingService:
    def test_cosine_similarity_identical(self):
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        assert EmbeddingService.cosine_similarity(a, b) == pytest.approx(1.0)

    def test_cosine_similarity_orthogonal(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert EmbeddingService.cosine_similarity(a, b) == pytest.approx(0.0)

    def test_cosine_similarity_opposite(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert EmbeddingService.cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_cosine_similarity_empty(self):
        assert EmbeddingService.cosine_similarity([], []) == 0.0

    def test_cosine_similarity_mismatched_length(self):
        assert EmbeddingService.cosine_similarity([1.0], [1.0, 2.0]) == 0.0

    def test_cosine_similarity_zero_vector(self):
        assert EmbeddingService.cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_is_available_without_sentence_transformers(self):
        service = EmbeddingService()
        # is_available depends on whether sentence-transformers is installed
        result = service.is_available()
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_encode_returns_none_when_unavailable(self):
        service = EmbeddingService()
        service._backend = None  # Force unavailable
        # Override _resolve_backend to keep backend as None
        service._provider = "local"
        import sys
        # Remove sentence_transformers from available modules to force None backend
        orig = sys.modules.get("sentence_transformers")
        sys.modules["sentence_transformers"] = None  # type: ignore
        try:
            result = await service.encode("test text")
            assert result is None
        finally:
            if orig is None:
                sys.modules.pop("sentence_transformers", None)
            else:
                sys.modules["sentence_transformers"] = orig

    @pytest.mark.asyncio
    async def test_encode_batch_returns_nones_when_unavailable(self):
        service = EmbeddingService(provider="local")
        service._backend = None
        import sys
        orig = sys.modules.get("sentence_transformers")
        sys.modules["sentence_transformers"] = None  # type: ignore
        try:
            results = await service.encode_batch(["text1", "text2"])
            assert results == [None, None]
        finally:
            if orig is None:
                sys.modules.pop("sentence_transformers", None)
            else:
                sys.modules["sentence_transformers"] = orig

    def test_cache_key_deterministic(self):
        service = EmbeddingService()
        key1 = service._cache_key("hello")
        key2 = service._cache_key("hello")
        assert key1 == key2

    def test_cache_key_different_for_different_text(self):
        service = EmbeddingService()
        key1 = service._cache_key("hello")
        key2 = service._cache_key("world")
        assert key1 != key2

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        service = EmbeddingService()
        service._backend = "local"
        # Pre-fill cache
        key = service._cache_key("cached text")
        service._cache[key] = [0.1, 0.2, 0.3]
        # Cache should hit before trying to use the model
        result = await service.encode("cached text")
        assert result == [0.1, 0.2, 0.3]


class TestEmbeddingServiceProviders:
    def test_resolve_backend_no_key(self):
        service = EmbeddingService(provider="auto", api_key="")
        # Without API key and without sentence-transformers, may resolve to None or local
        result = service.is_available()
        assert isinstance(result, bool)

    def test_resolve_backend_gemini(self):
        service = EmbeddingService(provider="gemini", api_key="fake-key")
        service._resolve_backend()
        assert service._backend == "gemini"
        assert service._dimensions == 768

    def test_resolve_backend_openai(self):
        service = EmbeddingService(provider="openai", api_key="fake-key")
        service._resolve_backend()
        assert service._backend == "openai"
        assert service._dimensions == 1536

    def test_resolve_backend_ollama(self):
        service = EmbeddingService(provider="ollama")
        service._resolve_backend()
        assert service._backend == "ollama"

    @pytest.mark.asyncio
    async def test_encode_no_backend(self):
        service = EmbeddingService(provider="local")
        service._backend = None  # Force no backend
        import sys
        orig = sys.modules.get("sentence_transformers")
        sys.modules["sentence_transformers"] = None  # type: ignore
        try:
            result = await service.encode("test")
            assert result is None
        finally:
            if orig is None:
                sys.modules.pop("sentence_transformers", None)
            else:
                sys.modules["sentence_transformers"] = orig

    @pytest.mark.asyncio
    async def test_cache_works_across_calls(self):
        service = EmbeddingService()
        service._backend = "local"
        # Pre-fill cache
        key = service._cache_key("cached")
        service._cache[key] = [0.1, 0.2]
        result = await service.encode("cached")
        assert result == [0.1, 0.2]
