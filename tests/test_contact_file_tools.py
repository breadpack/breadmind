"""Tests for contact and file LLM tools."""
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def mock_registry():
    from breadmind.personal.adapters.base import AdapterRegistry

    registry = AdapterRegistry()

    contact_adapter = AsyncMock()
    contact_adapter.domain = "contact"
    contact_adapter.source = "builtin"
    contact_adapter.list_items = AsyncMock(return_value=[])
    contact_adapter.create_item = AsyncMock(return_value="new-contact-id")
    registry.register(contact_adapter)

    file_adapter = AsyncMock()
    file_adapter.domain = "file"
    file_adapter.source = "builtin"
    file_adapter.list_items = AsyncMock(return_value=[])
    registry.register(file_adapter)

    return registry


@pytest.mark.asyncio
async def test_contact_search_empty(mock_registry):
    from breadmind.personal.tools import contact_search

    result = await contact_search(query="Bob", registry=mock_registry, user_id="alice")
    assert "찾을 수 없" in result


@pytest.mark.asyncio
async def test_contact_search_with_results(mock_registry):
    from breadmind.personal.tools import contact_search
    from breadmind.personal.models import Contact

    adapter = mock_registry.get_adapter("contact", "builtin")
    adapter.list_items.return_value = [
        Contact(id="c1", name="Bob Smith", email="bob@example.com", phone="010-1234"),
    ]
    result = await contact_search(query="Bob", registry=mock_registry, user_id="alice")
    assert "Bob Smith" in result
    assert "bob@example.com" in result


@pytest.mark.asyncio
async def test_contact_create(mock_registry):
    from breadmind.personal.tools import contact_create

    result = await contact_create(
        name="Alice",
        email="alice@example.com",
        registry=mock_registry,
        user_id="default",
    )
    assert "new-contact-id" in result


@pytest.mark.asyncio
async def test_file_search_empty(mock_registry):
    from breadmind.personal.tools import file_search

    result = await file_search(query="report", registry=mock_registry, user_id="alice")
    assert "찾을 수 없" in result


@pytest.mark.asyncio
async def test_file_search_with_results(mock_registry):
    from breadmind.personal.tools import file_search
    from breadmind.personal.models import File

    adapter = mock_registry.get_adapter("file", "builtin")
    adapter.list_items.return_value = [
        File(
            id="f1",
            name="report.pdf",
            path_or_url="/docs/report.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
        ),
    ]
    result = await file_search(query="report", registry=mock_registry, user_id="alice")
    assert "report.pdf" in result


@pytest.mark.asyncio
async def test_file_list(mock_registry):
    from breadmind.personal.tools import file_list

    result = await file_list(registry=mock_registry, user_id="alice")
    assert isinstance(result, str)
