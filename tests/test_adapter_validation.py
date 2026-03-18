"""Tests for adapter input validation during authentication."""
import pytest


@pytest.mark.asyncio
async def test_github_validates_repo():
    from breadmind.personal.adapters.github_issues import GitHubIssuesAdapter
    adapter = GitHubIssuesAdapter()
    # Empty credentials should fail
    result = await adapter.authenticate({"token": "", "owner": "", "repo": ""})
    assert result is False


@pytest.mark.asyncio
async def test_jira_requires_base_url():
    from breadmind.personal.adapters.jira import JiraAdapter
    adapter = JiraAdapter()
    result = await adapter.authenticate({"email": "a@b.com", "api_token": "tok"})
    assert result is False


@pytest.mark.asyncio
async def test_notion_requires_api_key():
    from breadmind.personal.adapters.notion import NotionAdapter
    adapter = NotionAdapter()
    result = await adapter.authenticate({})
    assert result is False
