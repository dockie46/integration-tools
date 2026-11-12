"""Minimal stand-in for the googleapiclient Calendar resource (records calls, returns canned data)."""

from __future__ import annotations

from typing import Any


class _Request:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    def execute(self) -> Any:
        if self._error:
            raise self._error
        return self._result


class _Events:
    def __init__(self, service: FakeCalendarService) -> None:
        self._s = service

    def list(self, **kwargs: Any) -> _Request:
        self._s.calls.append(("list", kwargs))
        if self._s.list_queue:
            nxt = self._s.list_queue.pop(0)
            return _Request(None, nxt) if isinstance(nxt, Exception) else _Request(nxt)
        key = kwargs.get("privateExtendedProperty")
        if key is not None:
            return _Request({"items": self._s.by_key.get(key, [])})
        return _Request({"items": self._s.window_items})

    def insert(self, **kwargs: Any) -> _Request:
        self._s.calls.append(("insert", kwargs))
        return _Request({"id": "new-1", **kwargs["body"]})

    def patch(self, **kwargs: Any) -> _Request:
        self._s.calls.append(("patch", kwargs))
        return _Request({"id": kwargs["eventId"], **kwargs["body"]})

    def delete(self, **kwargs: Any) -> _Request:
        self._s.calls.append(("delete", kwargs))
        return _Request(None, self._s.delete_error)


class _FreeBusy:
    def __init__(self, service: FakeCalendarService) -> None:
        self._s = service

    def query(self, body: dict) -> _Request:
        self._s.calls.append(("freebusy", body))
        return _Request(
            {
                "calendars": {
                    item["id"]: self._s.freebusy_data.get(item["id"], {"busy": []})
                    for item in body["items"]
                }
            }
        )


class _Calendars:
    def __init__(self, service: FakeCalendarService) -> None:
        self._s = service

    def insert(self, body: dict) -> _Request:
        self._s.calls.append(("calendars.insert", body))
        return _Request(
            {
                "id": "new-cal@group.calendar.google.com",
                "summary": body["summary"],
                "timeZone": body["timeZone"],
            }
        )


class _Acl:
    def __init__(self, service: FakeCalendarService) -> None:
        self._s = service

    def insert(self, **kwargs: Any) -> _Request:
        self._s.calls.append(("acl.insert", kwargs))
        return _Request({"id": "user:" + kwargs["body"]["scope"]["value"]})


class FakeCalendarService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.by_key: dict[str, list[dict]] = {}
        self.window_items: list[dict] = []
        self.freebusy_data: dict[str, dict] = {}
        self.delete_error: Exception | None = None
        self.list_queue: list[dict | Exception] = []

    def events(self) -> _Events:
        return _Events(self)

    def freebusy(self) -> _FreeBusy:
        return _FreeBusy(self)

    def calendars(self) -> _Calendars:
        return _Calendars(self)

    def acl(self) -> _Acl:
        return _Acl(self)
