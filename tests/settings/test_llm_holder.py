from breadmind.settings.llm_holder import LLMProviderHolder


class FakeProvider:
    def __init__(self, name):
        self.name = name

    async def complete(self, prompt):
        return f"{self.name}:{prompt}"


async def test_holder_delegates_attribute_access():
    h = LLMProviderHolder(FakeProvider("A"))
    assert h.name == "A"
    assert await h.complete("hi") == "A:hi"


async def test_holder_swap_changes_delegate():
    h = LLMProviderHolder(FakeProvider("A"))
    h.swap(FakeProvider("B"))
    assert h.name == "B"
    assert await h.complete("hi") == "B:hi"


async def test_holder_rejects_none_swap():
    h = LLMProviderHolder(FakeProvider("A"))
    import pytest
    with pytest.raises(ValueError):
        h.swap(None)
    assert h.name == "A"
