"""Minimal stand-in for the Graph HTTP transport (records calls, returns queued responses)."""

from __future__ import annotations

from typing import Any


class FakeResponse:
    def __init__(self, status_code: int = 200, body: Any = None, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self._body = {} if body is None else body
        self.headers = headers or {}

    @property
    def text(self) -> str:
        return "" if self._body == {} and self.status_code == 204 else "{...}"

    def json(self) -> Any:
        return self._body


class FakeTransport:
    """Pops one queued response per request, in order, and logs every call."""

    def __init__(self, responses: list[FakeResponse] | None = None) -> None:
        self.queue: list[FakeResponse] = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def push(self, *responses: FakeResponse) -> FakeTransport:
        self.queue.extend(responses)
        return self

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Any = None,
        json: Any = None,
        headers: Any = None,
    ) -> FakeResponse:
        self.calls.append(
            {"method": method, "url": url, "params": dict(params or {}), "json": json, "headers": dict(headers or {})}
        )
        if not self.queue:
            raise AssertionError(f"No queued response for {method} {url}")
        return self.queue.pop(0)
