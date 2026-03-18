# tests/test_jira_adapter.py
"""JiraAdapter unit tests using mock aiohttp."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest


_CREDENTIALS = {
    "base_url": "https://mycompany.atlassian.net",
    "email": "user@example.com",
    "api_token": "test-token",
    "project_key": "PROJ",
}

_SAMPLE_ISSUE = {
    "key": "PROJ-1",
    "id": "10001",
    "fields": {
        "summary": "Fix login bug",
        "status": {"name": "In Progress"},
        "priority": {"name": "High"},
        "duedate": "2026-04-01",
        "assignee": {"displayName": "Alice"},
    },
}


class _MockResponse:
    """Lightweight mock for aiohttp response used as async context manager."""

    def __init__(self, json_data: dict, status: int = 200) -> None:
        self._json_data = json_data
        self.status = status

    async def json(self) -> dict:
        return self._json_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class _MockSession:
    """Mock aiohttp.ClientSession supporting get/post/put/delete."""

    def __init__(self, response: _MockResponse) -> None:
        self._response = response
        self.last_method: str = ""
        self.last_url: str = ""
        self.last_kwargs: dict = {}

    def get(self, url, **kwargs):
        self.last_method, self.last_url, self.last_kwargs = "GET", url, kwargs
        return self._response

    def post(self, url, **kwargs):
        self.last_method, self.last_url, self.last_kwargs = "POST", url, kwargs
        return self._response

    def put(self, url, **kwargs):
        self.last_method, self.last_url, self.last_kwargs = "PUT", url, kwargs
        return self._response

    def delete(self, url, **kwargs):
        self.last_method, self.last_url, self.last_kwargs = "DELETE", url, kwargs
        return self._response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.fixture
def mock_session():
    """Return a factory that patches aiohttp.ClientSession with a _MockSession."""

    def _make(json_data: dict, status: int = 200):
        resp = _MockResponse(json_data, status)
        session = _MockSession(resp)
        patcher = patch(
            "aiohttp.ClientSession",
            return_value=session,
        )
        return patcher, session

    return _make


@pytest.mark.asyncio
async def test_authenticate_success():
    from breadmind.personal.adapters.jira import JiraAdapter

    adapter = JiraAdapter()
    result = await adapter.authenticate(_CREDENTIALS)
    assert result is True
    assert adapter._base_url == "https://mycompany.atlassian.net"
    assert adapter._auth_header.startswith("Basic ")


@pytest.mark.asyncio
async def test_authenticate_missing_fields():
    from breadmind.personal.adapters.jira import JiraAdapter

    adapter = JiraAdapter()
    result = await adapter.authenticate({"base_url": "https://x.atlassian.net"})
    assert result is False


@pytest.mark.asyncio
async def test_list_items(mock_session):
    from breadmind.personal.adapters.jira import JiraAdapter

    patcher, session = mock_session({"issues": [_SAMPLE_ISSUE]})
    adapter = JiraAdapter()
    await adapter.authenticate(_CREDENTIALS)

    with patcher:
        tasks = await adapter.list_items()

    assert len(tasks) == 1
    task = tasks[0]
    assert task.id == "PROJ-1"
    assert task.title == "Fix login bug"
    assert task.status == "in_progress"
    assert task.priority == "high"
    assert task.assignee == "Alice"
    assert session.last_method == "GET"
    assert "/rest/api/3/search" in session.last_url


@pytest.mark.asyncio
async def test_create_item(mock_session):
    from breadmind.personal.adapters.jira import JiraAdapter
    from breadmind.personal.models import Task

    patcher, session = mock_session({"key": "PROJ-42", "id": "10042"})
    adapter = JiraAdapter()
    await adapter.authenticate(_CREDENTIALS)

    task = Task(
        id="",
        title="New feature",
        description="Implement the thing",
        due_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    with patcher:
        result_key = await adapter.create_item(task)

    assert result_key == "PROJ-42"
    assert session.last_method == "POST"
    assert "/rest/api/3/issue" in session.last_url
    payload = session.last_kwargs.get("json", {})
    assert payload["fields"]["summary"] == "New feature"
    assert payload["fields"]["duedate"] == "2026-05-01"
    assert payload["fields"]["description"]["content"][0]["content"][0]["text"] == "Implement the thing"


@pytest.mark.asyncio
async def test_update_item(mock_session):
    from breadmind.personal.adapters.jira import JiraAdapter

    patcher, session = mock_session({}, status=204)
    adapter = JiraAdapter()
    await adapter.authenticate(_CREDENTIALS)

    with patcher:
        ok = await adapter.update_item("PROJ-1", {"title": "Updated title"})

    assert ok is True
    assert session.last_method == "PUT"
    payload = session.last_kwargs.get("json", {})
    assert payload["fields"]["summary"] == "Updated title"


@pytest.mark.asyncio
async def test_issue_to_task_mapping():
    from breadmind.personal.adapters.jira import JiraAdapter

    adapter = JiraAdapter()
    task = adapter._issue_to_task(_SAMPLE_ISSUE)

    assert task.id == "PROJ-1"
    assert task.source == "jira"
    assert task.source_id == "PROJ-1"
    assert task.title == "Fix login bug"
    assert task.status == "in_progress"
    assert task.priority == "high"
    assert task.due_at == datetime(2026, 4, 1, tzinfo=timezone.utc)
    assert task.assignee == "Alice"
