"""ConfluenceConnector tests (unit + vcr-backed integration)."""
from __future__ import annotations


import pytest

from breadmind.kb.connectors.confluence import (
    ConfluenceConnector,
    html_to_markdown,
)


class FakeVault:
    def __init__(self, mapping: dict[str, str]):
        self._m = mapping

    async def retrieve(self, cred_id: str) -> str | None:
        return self._m.get(cred_id)


async def test_connector_name_is_confluence():
    assert ConfluenceConnector.connector_name == "confluence"


async def test_basic_auth_header_uses_credential_vault(mem_db, fake_extractor,
                                                       fake_review_queue):
    vault = FakeVault({"confluence:pilot": "alice@example.com:TOKEN123"})
    conn = ConfluenceConnector(
        db=mem_db,
        base_url="https://example.atlassian.net/wiki",
        credentials_ref="confluence:pilot",
        extractor=fake_extractor,
        review_queue=fake_review_queue,
        vault=vault,
    )
    header = await conn._build_auth_header()
    # "alice@example.com:TOKEN123" -> base64
    assert header.startswith("Basic ")
    import base64
    decoded = base64.b64decode(header.removeprefix("Basic ")).decode()
    assert decoded == "alice@example.com:TOKEN123"


async def test_connector_raises_if_credential_missing(mem_db, fake_extractor,
                                                      fake_review_queue):
    vault = FakeVault({})
    conn = ConfluenceConnector(
        db=mem_db,
        base_url="https://example.atlassian.net/wiki",
        credentials_ref="confluence:missing",
        extractor=fake_extractor,
        review_queue=fake_review_queue,
        vault=vault,
    )
    with pytest.raises(RuntimeError, match="credential"):
        await conn._build_auth_header()


class _FakeResponse:
    def __init__(self, status: int, payload: dict, headers: dict | None = None):
        self.status = status
        self._payload = payload
        self.headers = headers or {}

    async def json(self):
        return self._payload

    def raise_for_status(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _ScriptedSession:
    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def get(self, url: str, **kw):
        self.calls.append((url, kw.get("params", {})))
        return self._responses.pop(0)

    async def close(self):
        self.closed = True


def _page_payload(results, next_path: str | None):
    out = {"results": results, "_links": {}}
    if next_path:
        out["_links"]["next"] = next_path
    return out


async def test_fetch_pages_paginates_until_next_absent(mem_db, fake_extractor,
                                                      fake_review_queue):
    vault = FakeVault({"confluence:x": "u:t"})
    session = _ScriptedSession([
        _FakeResponse(200, _page_payload(
            results=[{
                "id": "1", "title": "Page 1",
                "space": {"key": "SPACE"},
                "_links": {"webui": "/pages/1"},
                "body": {"storage": {"value": "<p>A</p>"}},
                "version": {"when": "2026-04-20T00:00:00.000Z"},
            }],
            next_path="/rest/api/content?start=50",
        )),
        _FakeResponse(200, _page_payload(
            results=[{
                "id": "2", "title": "Page 2",
                "space": {"key": "SPACE"},
                "_links": {"webui": "/pages/2"},
                "body": {"storage": {"value": "<p>B</p>"}},
                "version": {"when": "2026-04-20T01:00:00.000Z"},
            }],
            next_path=None,
        )),
    ])
    conn = ConfluenceConnector(
        db=mem_db, base_url="https://example.atlassian.net/wiki",
        credentials_ref="confluence:x",
        extractor=fake_extractor, review_queue=fake_review_queue,
        vault=vault, session=session,
    )
    pages = []
    async for p in conn._fetch_pages("SPACE", cursor=None):
        pages.append(p)

    assert [p.id for p in pages] == ["1", "2"]
    assert pages[0].storage_html == "<p>A</p>"
    assert pages[1].web_url.endswith("/pages/2")
    assert len(session.calls) == 2
    # First call must include spaceKey and expand
    first_url, first_params = session.calls[0]
    assert "spaceKey" in first_params and first_params["spaceKey"] == "SPACE"
    assert "body.storage,version" in first_params.get("expand", "")


async def test_fetch_pages_includes_updated_since_when_cursor_set(
    mem_db, fake_extractor, fake_review_queue
):
    vault = FakeVault({"confluence:x": "u:t"})
    session = _ScriptedSession([
        _FakeResponse(200, _page_payload(results=[], next_path=None))
    ])
    conn = ConfluenceConnector(
        db=mem_db, base_url="https://example.atlassian.net/wiki",
        credentials_ref="confluence:x",
        extractor=fake_extractor, review_queue=fake_review_queue,
        vault=vault, session=session,
    )
    async for _ in conn._fetch_pages("SPACE", cursor="2026-04-20T00:00:00Z"):
        pass
    _, params = session.calls[0]
    # CQL-style filter — accept either "updated-since" param or CQL mode.
    assert params.get("updated-since") == "2026-04-20T00:00:00Z"


async def test_429_honors_retry_after_header(mem_db, fake_extractor,
                                              fake_review_queue, monkeypatch):
    """First response 429 with Retry-After=2, then success."""
    vault = FakeVault({"confluence:x": "u:t"})
    session = _ScriptedSession([
        _FakeResponse(429, {}, headers={"Retry-After": "2"}),
        _FakeResponse(200, _page_payload(results=[], next_path=None)),
    ])
    conn = ConfluenceConnector(
        db=mem_db, base_url="https://example.atlassian.net/wiki",
        credentials_ref="confluence:x",
        extractor=fake_extractor, review_queue=fake_review_queue,
        vault=vault, session=session,
    )

    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr("breadmind.kb.connectors.confluence.asyncio.sleep",
                        fake_sleep)
    async for _ in conn._fetch_pages("S", cursor=None):
        pass

    assert slept == [2]
    assert len(session.calls) == 2


async def test_429_without_retry_after_uses_exponential_defaults(
    mem_db, fake_extractor, fake_review_queue, monkeypatch
):
    vault = FakeVault({"confluence:x": "u:t"})
    session = _ScriptedSession([
        _FakeResponse(429, {}, headers={}),
        _FakeResponse(429, {}, headers={}),
        _FakeResponse(429, {}, headers={}),
        _FakeResponse(200, _page_payload(results=[], next_path=None)),
    ])
    conn = ConfluenceConnector(
        db=mem_db, base_url="https://example.atlassian.net/wiki",
        credentials_ref="confluence:x",
        extractor=fake_extractor, review_queue=fake_review_queue,
        vault=vault, session=session,
    )
    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr("breadmind.kb.connectors.confluence.asyncio.sleep",
                        fake_sleep)
    async for _ in conn._fetch_pages("S", cursor=None):
        pass
    # First three 429s use the built-in schedule 60, 300, 1800
    assert slept == [60, 300, 1800]


def test_markdownify_converts_code_blocks():
    html = '<pre><code class="language-python">print("hi")</code></pre>'
    out = html_to_markdown(html)
    assert "```" in out
    assert 'print("hi")' in out


def test_markdownify_converts_tables_to_markdown():
    html = (
        "<table>"
        "<thead><tr><th>Col1</th><th>Col2</th></tr></thead>"
        "<tbody><tr><td>a</td><td>b</td></tr></tbody>"
        "</table>"
    )
    out = html_to_markdown(html)
    # Pipe-delimited table representation
    assert "|" in out
    assert "Col1" in out and "Col2" in out
    assert "a" in out and "b" in out


def test_markdownify_preserves_links():
    html = '<p>see <a href="https://example.com/x">here</a></p>'
    out = html_to_markdown(html)
    assert "[here](https://example.com/x)" in out


async def test_sync_processes_pages_and_advances_cursor(
    mem_db, fake_extractor, fake_review_queue, project_id
):
    vault = FakeVault({"confluence:x": "u:t"})
    session = _ScriptedSession([
        _FakeResponse(200, _page_payload(
            results=[
                {
                    "id": "10", "title": "Runbook A",
                    "space": {"key": "SPACE"},
                    "_links": {"webui": "/pages/10"},
                    "body": {"storage": {"value": "<h1>A</h1><p>Steps</p>"}},
                    "version": {"when": "2026-04-20T05:00:00.000Z"},
                },
                {
                    "id": "11", "title": "Runbook B",
                    "space": {"key": "SPACE"},
                    "_links": {"webui": "/pages/11"},
                    "body": {"storage": {"value": "<p>B</p>"}},
                    "version": {"when": "2026-04-20T06:30:00.000Z"},
                },
            ],
            next_path=None,
        )),
    ])
    conn = ConfluenceConnector(
        db=mem_db, base_url="https://example.atlassian.net/wiki",
        credentials_ref="confluence:x",
        extractor=fake_extractor, review_queue=fake_review_queue,
        vault=vault, session=session,
    )

    result = await conn.sync(project_id, "SPACE", cursor=None)

    assert result.processed == 2
    assert result.errors == 0
    # Cursor advances to max(version.when)
    assert result.new_cursor == "2026-04-20T06:30:00.000Z"

    # Extractor received two calls, with source_meta populated per spec §6.3
    assert len(fake_extractor.calls) == 2
    meta0 = fake_extractor.calls[0].source_meta
    assert meta0.source_type == "confluence"
    assert meta0.source_ref == "10"
    assert meta0.extracted_from == "confluence_sync"
    assert meta0.original_user is None
    assert meta0.project_id == project_id
    assert meta0.source_uri.endswith("/pages/10")

    # Each extracted candidate was enqueued
    assert len(fake_review_queue.enqueued) == 2
