"""Microsoft Graph HTTP transport: auth header, retries and error mapping in one place.

The client talks to Graph through a small :class:`Transport` (one ``request`` method), so tests inject a fake
and never hit the network. Error mapping is central: 401/403 become a reconnect-level auth error, 404/410 carry
their status for the worker to turn into ``notFound``, 429/503 are retried.
"""

from __future__ import annotations

import random
import time
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import urljoin

from .auth import GRAPH_BASE_URL, MicrosoftAuthError, TokenProvider

_RETRY_STATUSES = (429, 503)
_MAX_RETRIES = 5


class GraphApiError(RuntimeError):
    """Graph refused a request. ``status`` is the HTTP status (404 gone, 410 delta expired, …)."""

    def __init__(self, message: str, status: int | None = None, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class GraphAuthError(MicrosoftAuthError):
    """Graph rejected the token or the app lacks consent/permission (401/403): connect the account again."""


class Response(Protocol):
    status_code: int
    headers: Mapping[str, str]
    text: str

    def json(self) -> Any: ...


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response: ...


class RequestsTransport:
    """The real transport: a ``requests`` session that attaches a fresh app-only bearer on every call."""

    def __init__(self, token_provider: TokenProvider, session: Any) -> None:
        self._token_provider = token_provider
        self._session = session

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        merged = {"Authorization": f"Bearer {self._token_provider.token()}"}
        if headers:
            merged.update(headers)
        return self._session.request(method, url, params=params, json=json, headers=merged, timeout=30)


def _error_message(body: Any, status: int) -> tuple[str, str]:
    if isinstance(body, Mapping):
        error = body.get("error")
        if isinstance(error, Mapping):
            return str(error.get("message") or f"HTTP {status}"), str(error.get("code") or "")
    return f"HTTP {status}", ""


class GraphClient:
    """Thin wrapper over the Graph REST API used by the calendar reads and writes."""

    def __init__(self, transport: Transport, *, base_url: str = GRAPH_BASE_URL) -> None:
        self._transport = transport
        self._base_url = base_url.rstrip("/") + "/"

    def get(self, path: str, *, params: Mapping[str, Any] | None = None, prefer: str | None = None) -> dict:
        return self._send("GET", self._url(path), params=params, prefer=prefer)

    def get_url(self, url: str, *, prefer: str | None = None) -> dict:
        """Follow an absolute ``@odata.nextLink`` / ``@odata.deltaLink`` as Graph returned it."""
        return self._send("GET", url, prefer=prefer)

    def post(self, path: str, body: Any, *, prefer: str | None = None) -> dict:
        return self._send("POST", self._url(path), json=body, prefer=prefer)

    def patch(self, path: str, body: Any) -> dict:
        return self._send("PATCH", self._url(path), json=body)

    def delete(self, path: str) -> dict:
        return self._send("DELETE", self._url(path))

    def _url(self, path: str) -> str:
        return path if path.startswith("http") else urljoin(self._base_url, path.lstrip("/"))

    def _send(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        prefer: str | None = None,
    ) -> dict:
        headers = {"Prefer": prefer} if prefer else None
        delay = 1.0
        for attempt in range(_MAX_RETRIES + 1):
            response = self._transport.request(method, url, params=params, json=json, headers=headers)
            status = response.status_code
            if status in _RETRY_STATUSES and attempt < _MAX_RETRIES:
                time.sleep(_retry_after(response) or delay + random.uniform(0, delay))
                delay = min(delay * 2, 60.0)
                continue
            if 200 <= status < 300:
                if status == 204 or not (response.text or "").strip():
                    return {}
                body = response.json()
                return body if isinstance(body, dict) else {"value": body}
            body = _safe_json(response)
            message, code = _error_message(body, status)
            if status in (401, 403):
                raise GraphAuthError(f"Microsoft Graph refused access: {message}")
            raise GraphApiError(f"Microsoft Graph request failed: {message}", status, code)
        raise GraphApiError("Microsoft Graph request failed after retries", None)


def _retry_after(response: Response) -> float | None:
    raw = (response.headers or {}).get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _safe_json(response: Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None
