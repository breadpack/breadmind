"""Unit tests for the VCR ``before_record_response`` secret scrubber.

These guard against an operator accidentally committing secrets in a
newly recorded cassette. ``_scrub_response_body`` runs only during VCR
record modes; replay-only (``record_mode="none"``) never invokes it.
"""
from __future__ import annotations


def _body(raw: bytes | str) -> dict:
    return {"body": {"string": raw}}


def test_scrubs_plain_email(scrub_response_body):
    resp = _body(b'{"author":"alice@example.com","text":"hello"}')
    out = scrub_response_body(resp)
    assert b"alice@example.com" not in out["body"]["string"]
    assert b"scrubbed@example.com" in out["body"]["string"]


def test_scrubs_atlassian_api_token(scrub_response_body):
    token = b"ATATT" + b"3xFfGF0T1XkYq7zZ9aBcDeFgHiJkLmNo"
    out = scrub_response_body(_body(b'{"x":"' + token + b'"}'))
    assert token not in out["body"]["string"]
    assert b"ATATT_REDACTED" in out["body"]["string"]


def test_scrubs_bearer_style_json_keys(scrub_response_body):
    resp = _body(b'{"access_token":"eyJhbGci.xxx.yyy","n":1}')
    out = scrub_response_body(resp)
    assert b"eyJhbGci.xxx.yyy" not in out["body"]["string"]
    assert b'"access_token": "REDACTED"' in out["body"]["string"]


def test_scrubs_slack_token(scrub_response_body):
    resp = _body(b'{"tok":"xoxb-1234567890-abcdefghij"}')
    out = scrub_response_body(resp)
    assert b"xoxb-1234567890" not in out["body"]["string"]
    assert b"xoxb-REDACTED" in out["body"]["string"]


def test_scrubs_string_body_returns_string(scrub_response_body):
    """If VCR gives us a str body (not bytes), we should return str back."""
    resp = _body("user@example.com here")
    out = scrub_response_body(resp)
    assert isinstance(out["body"]["string"], str)
    assert "user@example.com" not in out["body"]["string"]


def test_no_body_string_is_noop(scrub_response_body):
    resp = {"body": {}}
    out = scrub_response_body(resp)
    assert out == {"body": {}}


def test_empty_body_is_noop(scrub_response_body):
    resp = _body(b"")
    out = scrub_response_body(resp)
    assert out["body"]["string"] == b""


def test_clean_body_untouched(scrub_response_body):
    resp = _body(b'{"results":[{"id":"123"}]}')
    out = scrub_response_body(resp)
    assert out["body"]["string"] == b'{"results":[{"id":"123"}]}'
