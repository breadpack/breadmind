import json
from breadmind.messenger.errors import (
    MessengerError, RateLimited, NotFound, Forbidden, Unauthorized, ValidationFailed,
    error_to_response,
)


def test_rate_limited_response():
    err = RateLimited(retry_after_seconds=12)
    r = error_to_response(err, trace_id="abc")
    assert r.status_code == 429
    body = json.loads(r.body)
    assert body["code"] == "rate_limited"
    assert body["status"] == 429
    assert body["retry_after_seconds"] == 12
    assert body["trace_id"] == "abc"
    assert r.headers["retry-after"] == "12"


def test_not_found():
    err = NotFound("channel", "C123")
    r = error_to_response(err)
    assert r.status_code == 404
    body = json.loads(r.body)
    assert body["code"] == "not_found"


def test_forbidden():
    r = error_to_response(Forbidden("cannot post"))
    assert r.status_code == 403


def test_unauthorized():
    r = error_to_response(Unauthorized())
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Bearer"


def test_validation_failed():
    err = ValidationFailed([{"field": "name", "msg": "required"}])
    r = error_to_response(err)
    assert r.status_code == 422
