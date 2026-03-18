# tests/test_github_issues_adapter.py
"""GitHubIssuesAdapter unit tests using mock aiohttp."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_response(status=200, json_data=None):
    """Create a mock aiohttp response."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    return resp


def _make_session(response):
    """Create a mock aiohttp.ClientSession context manager."""
    session = AsyncMock()
    # Each HTTP method returns an async context manager yielding the response
    for method in ("get", "post", "patch", "put", "delete"):
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=response)
        cm.__aexit__ = AsyncMock(return_value=False)
        setattr(session, method, MagicMock(return_value=cm))
    return session


def _session_ctx(session):
    """Wrap a mock session as an async context manager."""
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


SAMPLE_ISSUE = {
    "number": 42,
    "title": "Fix login bug",
    "body": "Users cannot login",
    "state": "open",
    "labels": [{"name": "bug"}, {"name": "priority:high"}],
    "assignees": [{"login": "alice"}],
}

SAMPLE_PR = {
    "number": 99,
    "title": "Add feature",
    "body": "New feature",
    "state": "open",
    "labels": [],
    "assignees": [],
    "pull_request": {"url": "https://api.github.com/repos/o/r/pulls/99"},
}


def _mock_aiohttp_session_for_auth(status=200, json_data=None):
    """Patch aiohttp.ClientSession so authenticate() doesn't make real HTTP calls."""
    resp = _make_response(status=status, json_data=json_data)
    session = _make_session(resp)
    return patch("aiohttp.ClientSession", return_value=_session_ctx(session))


@pytest.fixture
async def adapter():
    from breadmind.personal.adapters.github_issues import GitHubIssuesAdapter

    a = GitHubIssuesAdapter()
    with _mock_aiohttp_session_for_auth(status=200):
        await a.authenticate({"token": "ghp_test", "owner": "myorg", "repo": "myrepo"})
    return a


@pytest.mark.asyncio
async def test_authenticate_success():
    from breadmind.personal.adapters.github_issues import GitHubIssuesAdapter

    a = GitHubIssuesAdapter()
    with _mock_aiohttp_session_for_auth(status=200):
        result = await a.authenticate(
            {"token": "ghp_test", "owner": "myorg", "repo": "myrepo"}
        )
    assert result is True
    assert a.domain == "task"
    assert a.source == "github"


@pytest.mark.asyncio
async def test_authenticate_missing_fields():
    from breadmind.personal.adapters.github_issues import GitHubIssuesAdapter

    a = GitHubIssuesAdapter()
    assert await a.authenticate({"token": "ghp_test"}) is False
    assert await a.authenticate({"owner": "o", "repo": "r"}) is False
    assert await a.authenticate({}) is False


@pytest.mark.asyncio
async def test_list_items_filters_pull_requests(adapter):
    resp = _make_response(json_data=[SAMPLE_ISSUE, SAMPLE_PR])
    session = _make_session(resp)

    with patch("aiohttp.ClientSession", return_value=_session_ctx(session)):
        tasks = await adapter.list_items()

    assert len(tasks) == 1
    assert tasks[0].title == "Fix login bug"
    assert tasks[0].id == "42"
    assert tasks[0].source == "github"


@pytest.mark.asyncio
async def test_list_items_with_status_filter(adapter):
    resp = _make_response(json_data=[])
    session = _make_session(resp)

    with patch("aiohttp.ClientSession", return_value=_session_ctx(session)):
        await adapter.list_items(filters={"status": "done"})

    # Verify the GET was called with state=closed
    call_args = session.get.call_args
    assert call_args is not None
    params = call_args[1].get("params") or call_args.kwargs.get("params", {})
    assert params.get("state") == "closed"


@pytest.mark.asyncio
async def test_create_item(adapter):
    from breadmind.personal.models import Task

    resp = _make_response(status=201, json_data={"number": 100})
    session = _make_session(resp)

    task = Task(
        id="",
        title="New issue",
        description="Description here",
        tags=["enhancement"],
        assignee="bob",
    )

    with patch("aiohttp.ClientSession", return_value=_session_ctx(session)):
        result_id = await adapter.create_item(task)

    assert result_id == "100"
    call_args = session.post.call_args
    payload = call_args[1].get("json") or call_args.kwargs.get("json", {})
    assert payload["title"] == "New issue"
    assert payload["body"] == "Description here"
    assert payload["labels"] == ["enhancement"]
    assert payload["assignees"] == ["bob"]


@pytest.mark.asyncio
async def test_update_item(adapter):
    resp = _make_response(status=200)
    session = _make_session(resp)

    with patch("aiohttp.ClientSession", return_value=_session_ctx(session)):
        result = await adapter.update_item("42", {"status": "done", "title": "Fixed"})

    assert result is True
    call_args = session.patch.call_args
    payload = call_args[1].get("json") or call_args.kwargs.get("json", {})
    assert payload["state"] == "closed"
    assert payload["title"] == "Fixed"


@pytest.mark.asyncio
async def test_update_item_empty_changes(adapter):
    result = await adapter.update_item("42", {})
    assert result is False


@pytest.mark.asyncio
async def test_issue_to_task_mapping():
    from breadmind.personal.adapters.github_issues import GitHubIssuesAdapter

    a = GitHubIssuesAdapter()
    task = a._issue_to_task(SAMPLE_ISSUE)

    assert task.id == "42"
    assert task.title == "Fix login bug"
    assert task.description == "Users cannot login"
    assert task.status == "pending"
    assert task.priority == "high"
    assert task.source == "github"
    assert task.source_id == "42"
    assert task.assignee == "alice"
    assert "bug" in task.tags
    assert "priority:high" in task.tags


@pytest.mark.asyncio
async def test_issue_to_task_closed_no_assignee():
    from breadmind.personal.adapters.github_issues import GitHubIssuesAdapter

    a = GitHubIssuesAdapter()
    issue = {
        "number": 7,
        "title": "Done task",
        "body": None,
        "state": "closed",
        "labels": [],
        "assignees": [],
    }
    task = a._issue_to_task(issue)

    assert task.status == "done"
    assert task.priority == "medium"
    assert task.assignee is None
    assert task.description == ""


@pytest.mark.asyncio
async def test_get_item_found(adapter):
    resp = _make_response(status=200, json_data=SAMPLE_ISSUE)
    session = _make_session(resp)

    with patch("aiohttp.ClientSession", return_value=_session_ctx(session)):
        task = await adapter.get_item("42")

    assert task is not None
    assert task.title == "Fix login bug"


@pytest.mark.asyncio
async def test_get_item_not_found(adapter):
    resp = _make_response(status=404)
    session = _make_session(resp)

    with patch("aiohttp.ClientSession", return_value=_session_ctx(session)):
        task = await adapter.get_item("9999")

    assert task is None


@pytest.mark.asyncio
async def test_delete_item_closes_issue(adapter):
    resp = _make_response(status=200)
    session = _make_session(resp)

    with patch("aiohttp.ClientSession", return_value=_session_ctx(session)):
        result = await adapter.delete_item("42")

    assert result is True
    call_args = session.patch.call_args
    payload = call_args[1].get("json") or call_args.kwargs.get("json", {})
    assert payload["state"] == "closed"
