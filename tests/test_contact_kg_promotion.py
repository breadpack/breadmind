"""Tests for Contact -> KGEntity promotion."""
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_promote_contact_basic():
    from breadmind.memory.context_builder import ContextBuilder
    from breadmind.personal.models import Contact

    semantic = AsyncMock()
    semantic.upsert_entity = AsyncMock()
    semantic.add_relation = AsyncMock()

    cb = ContextBuilder(working_memory=MagicMock(), semantic_memory=semantic)

    contact = Contact(id="c1", name="Alice", email="alice@example.com")
    entities = await cb.promote_contacts_to_kg([contact])

    assert len(entities) == 1
    assert entities[0].entity_type == "person"
    assert entities[0].name == "Alice"
    semantic.upsert_entity.assert_called_once()


@pytest.mark.asyncio
async def test_promote_contact_with_org():
    from breadmind.memory.context_builder import ContextBuilder
    from breadmind.personal.models import Contact

    semantic = AsyncMock()
    semantic.upsert_entity = AsyncMock()
    semantic.add_relation = AsyncMock()

    cb = ContextBuilder(working_memory=MagicMock(), semantic_memory=semantic)

    contact = Contact(id="c2", name="Bob", organization="Acme Corp")
    entities = await cb.promote_contacts_to_kg([contact])

    assert len(entities) == 1
    # Should create org entity + relation
    assert semantic.upsert_entity.call_count == 2  # person + org
    semantic.add_relation.assert_called_once()


@pytest.mark.asyncio
async def test_promote_no_semantic_memory():
    from breadmind.memory.context_builder import ContextBuilder
    from breadmind.personal.models import Contact

    cb = ContextBuilder(working_memory=MagicMock(), semantic_memory=None)
    contact = Contact(id="c3", name="Carol")
    entities = await cb.promote_contacts_to_kg([contact])
    assert entities == []


@pytest.mark.asyncio
async def test_promote_contact_with_platforms():
    from breadmind.memory.context_builder import ContextBuilder
    from breadmind.personal.models import Contact

    semantic = AsyncMock()
    semantic.upsert_entity = AsyncMock()

    cb = ContextBuilder(working_memory=MagicMock(), semantic_memory=semantic)

    contact = Contact(id="c4", name="Dave", platform_ids={"telegram": "123", "slack": "U456"})
    entities = await cb.promote_contacts_to_kg([contact])

    assert len(entities) == 1
    props = entities[0].properties
    assert "platforms" in props
    assert props["platforms"]["telegram"] == "123"


@pytest.mark.asyncio
async def test_promote_handles_errors_gracefully():
    from breadmind.memory.context_builder import ContextBuilder
    from breadmind.personal.models import Contact

    semantic = AsyncMock()
    semantic.upsert_entity = AsyncMock(side_effect=RuntimeError("DB error"))

    cb = ContextBuilder(working_memory=MagicMock(), semantic_memory=semantic)

    contact = Contact(id="c5", name="Eve")
    entities = await cb.promote_contacts_to_kg([contact])
    assert entities == []  # Error handled, no crash
