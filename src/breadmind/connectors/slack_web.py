"""Production Slack web-API session for KB backfill.

The :class:`breadmind.kb.backfill.slack.SlackBackfillAdapter` calls
``await session.call(method, **params)`` and reads the returned dict's
``ok`` / ``error`` / ``_status`` / ``_retry_after`` keys. ``_status=429``
plus ``_retry_after`` (seconds) drive the adapter's exponential backoff
in :meth:`_call_with_retry`.

This module implements that contract on top of slack-sdk's
:class:`AsyncWebClient`. Bot tokens are loaded lazily from the credential
vault on the first ``call()`` and the client is cached for the lifetime
of the session.
"""
from __future__ import annotations

from typing import Any, Callable


class SlackWebSession:
    """slack-sdk-shaped session backed by a vaulted bot token.

    Constructor arguments:

    ``vault``
        Object exposing ``await vault.retrieve(credential_id)`` returning
        the plaintext token (or ``None`` when missing).
    ``credentials_ref``
        Vault key for the bot token, e.g. ``"slack:org:<org_uuid>"``.
    ``client_factory`` (testing seam)
        Optional ``token -> client`` callable. When ``None`` (production)
        a real :class:`slack_sdk.web.async_client.AsyncWebClient` is built
        on first use. Tests inject a fake client so unit tests don't make
        HTTP calls.
    ``slack_api_error`` (testing seam)
        Exception class to catch around ``api_call``. Defaults to the real
        :class:`slack_sdk.errors.SlackApiError` resolved lazily; tests pass
        a fake error class with the same ``response`` shape.
    """

    def __init__(
        self,
        *,
        vault: Any,
        credentials_ref: str,
        client_factory: Callable[[str], Any] | None = None,
        slack_api_error: type[Exception] | None = None,
    ) -> None:
        self._vault = vault
        self._credentials_ref = credentials_ref
        self._client_factory = client_factory
        self._slack_api_error_cls: type[Exception] | None = slack_api_error
        self._client: Any | None = None

    async def call(self, method: str, **params: Any) -> dict[str, Any]:
        client = await self._ensure_client()
        err_cls = self._resolve_error_cls()
        try:
            response = await client.api_call(method, params=params)
        except err_cls as exc:
            return self._error_to_dict(exc)
        data = getattr(response, "data", response)
        return dict(data)

    async def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        token = await self._vault.retrieve(self._credentials_ref)
        if not token:
            raise RuntimeError(
                f"Slack token not found in vault: {self._credentials_ref}"
            )
        if self._client_factory is not None:
            self._client = self._client_factory(token)
        else:
            from slack_sdk.web.async_client import AsyncWebClient  # noqa: PLC0415
            self._client = AsyncWebClient(token=token)
        return self._client

    def _resolve_error_cls(self) -> type[Exception]:
        if self._slack_api_error_cls is None:
            from slack_sdk.errors import SlackApiError  # noqa: PLC0415
            self._slack_api_error_cls = SlackApiError
        return self._slack_api_error_cls

    def _error_to_dict(self, exc: Exception) -> dict[str, Any]:
        resp = getattr(exc, "response", None)
        if resp is None:
            return {"ok": False, "error": str(exc)}
        data: dict[str, Any] = dict(getattr(resp, "data", {}) or {})
        status = getattr(resp, "status_code", None)
        if status == 429:
            data["_status"] = 429
            retry = (getattr(resp, "headers", None) or {}).get("Retry-After")
            if retry is not None:
                try:
                    data["_retry_after"] = int(retry)
                except (TypeError, ValueError):
                    pass
        return data
