import pytest
from unittest.mock import AsyncMock
from breadmind.core.protocols import Message, Episode
from breadmind.plugins.builtin.memory.dreamer import Dreamer, DreamResult


@pytest.mark.asyncio
async def test_dream_with_messages():
    dreamer = Dreamer()
    messages = [
        Message(role="user", content="Check K8s pods"),
        Message(role="assistant", content="Found 3 pods running"),
        Message(role="user", content="Restart nginx pod"),
        Message(role="assistant", content="Pod restarted successfully"),
    ]
    result = await dreamer.dream("s1", messages)
    assert isinstance(result, DreamResult)
    assert result.new_episodes == 2
    assert result.session_id == "s1"


@pytest.mark.asyncio
async def test_dream_empty_messages():
    dreamer = Dreamer()
    result = await dreamer.dream("s1", [])
    assert result.new_episodes == 0


@pytest.mark.asyncio
async def test_dream_saves_to_episodic():
    episodic = AsyncMock()
    episodic.episodic_search = AsyncMock(return_value=[])
    episodic.episodic_save = AsyncMock()
    dreamer = Dreamer(episodic_memory=episodic)
    messages = [
        Message(role="user", content="What is the status?"),
        Message(role="assistant", content="All systems operational"),
    ]
    await dreamer.dream("s1", messages)
    assert episodic.episodic_save.call_count >= 1


@pytest.mark.asyncio
async def test_consolidate_deduplication():
    dreamer = Dreamer()
    existing = [Episode(id="e1", content="K8s check", keywords=["k8s", "pods", "check"])]
    new = [Episode(id="e2", content="K8s pod check", keywords=["k8s", "pods", "check", "status"])]
    consolidated = dreamer._consolidate(existing, new)
    # High overlap should prevent adding
    assert len(consolidated) == 1


@pytest.mark.asyncio
async def test_consolidate_adds_unique():
    dreamer = Dreamer()
    existing = [Episode(id="e1", content="K8s check", keywords=["k8s", "pods"])]
    new = [Episode(id="e2", content="Proxmox VM", keywords=["proxmox", "vm", "status"])]
    consolidated = dreamer._consolidate(existing, new)
    assert len(consolidated) == 2


def test_extract_keywords():
    dreamer = Dreamer()
    keywords = dreamer._extract_keywords("Check the Kubernetes pods and restart nginx deployment")
    assert len(keywords) > 0
    assert any("kubernetes" in k or "pods" in k or "nginx" in k for k in keywords)
