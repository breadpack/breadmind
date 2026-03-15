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
        service._available = False  # Force unavailable
        result = await service.encode("test text")
        assert result is None

    @pytest.mark.asyncio
    async def test_encode_batch_returns_nones_when_unavailable(self):
        service = EmbeddingService()
        service._available = False
        results = await service.encode_batch(["text1", "text2"])
        assert results == [None, None]

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
        service._available = False  # Don't need real model
        # Pre-fill cache
        key = service._cache_key("cached text")
        service._cache[key] = [0.1, 0.2, 0.3]
        service._available = True  # But cache should hit before model
        result = await service.encode("cached text")
        # Should return cached value without needing model
        assert result == [0.1, 0.2, 0.3]
