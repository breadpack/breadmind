"""RFC 7807 problem+json error responses."""
from __future__ import annotations
import json
from typing import Any
from fastapi import Response

_BASE_TYPE = "https://breadmind.app/errors/"


class MessengerError(Exception):
    code: str = "internal_error"
    status: int = 500
    title: str = "Internal Server Error"

    def __init__(self, detail: str | None = None, **extra: Any):
        super().__init__(detail or self.title)
        self.detail = detail
        self.extra = extra


class Unauthorized(MessengerError):
    code = "unauthenticated"
    status = 401
    title = "Authentication required"


class Forbidden(MessengerError):
    code = "forbidden"
    status = 403
    title = "Forbidden"


class NotFound(MessengerError):
    code = "not_found"
    status = 404
    title = "Not Found"

    def __init__(self, entity_kind: str, entity_id: str):
        super().__init__(
            f"{entity_kind} {entity_id} not found",
            entity_kind=entity_kind, entity_id=entity_id,
        )


class Conflict(MessengerError):
    code = "conflict"
    status = 409
    title = "Conflict"


class ValidationFailed(MessengerError):
    code = "validation_failed"
    status = 422
    title = "Unprocessable Entity"

    def __init__(self, errors: list[dict]):
        super().__init__("validation failed", errors=errors)


class RateLimited(MessengerError):
    code = "rate_limited"
    status = 429
    title = "Rate Limit Exceeded"

    def __init__(self, retry_after_seconds: int):
        super().__init__(
            f"retry after {retry_after_seconds}s",
            retry_after_seconds=retry_after_seconds,
        )


def error_to_response(err: MessengerError, *, trace_id: str | None = None) -> Response:
    body = {
        "type": _BASE_TYPE + err.code,
        "title": err.title,
        "status": err.status,
        "code": err.code,
    }
    if err.detail:
        body["detail"] = err.detail
    if trace_id:
        body["trace_id"] = trace_id
    body.update(err.extra)

    headers: dict[str, str] = {}
    if isinstance(err, Unauthorized):
        headers["WWW-Authenticate"] = "Bearer"
    if isinstance(err, RateLimited):
        headers["Retry-After"] = str(err.extra["retry_after_seconds"])

    return Response(
        content=json.dumps(body).encode(),
        status_code=err.status,
        media_type="application/problem+json",
        headers=headers,
    )
