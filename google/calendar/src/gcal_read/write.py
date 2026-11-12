"""Calendar writes, free/busy and time-window reads for apps that sync their own records.

Every written event carries ``EventInput.external_key`` in a private extended property, so the app can
find, update and delete "its" event without storing Google's event id (and a retry never duplicates it).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError

from .api import EXTERNAL_KEY_PROPERTY, _execute_with_retry, list_events, parse_event
from .models import BusyInterval, CalendarEvent, EventInput, FreeBusy

FREEBUSY_MAX_CALENDARS = 50


class CalendarApiError(RuntimeError):
    """Google Calendar refused a request. ``status`` is the HTTP status (403 no access, 404 no calendar, …)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _status(exc: HttpError) -> int | None:
    return getattr(getattr(exc, "resp", None), "status", None)


def _api_error(action: str, exc: HttpError) -> CalendarApiError:
    status = _status(exc)
    reason = {
        403: "no permission for this calendar",
        404: "calendar or event not found",
    }.get(status or 0, str(exc))
    return CalendarApiError(f"Calendar {action} failed: {reason}", status)


def to_rfc3339(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("Calendar times must be timezone-aware.")
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def event_body(event: EventInput) -> dict[str, Any]:
    """Google event resource for ``event``. Times are sent in ``event.time_zone`` so Google shows them local."""
    return {
        "summary": event.summary,
        "description": event.description,
        "location": event.location,
        "start": {"dateTime": to_rfc3339(event.start), "timeZone": event.time_zone},
        "end": {"dateTime": to_rfc3339(event.end), "timeZone": event.time_zone},
        "transparency": "opaque" if event.busy else "transparent",
        "extendedProperties": {"private": {EXTERNAL_KEY_PROPERTY: event.external_key}},
    }


def find_event_by_key(
    service: Resource, calendar_id: str, external_key: str
) -> dict[str, Any] | None:
    """The live event this app wrote under ``external_key``, or None."""
    try:
        response = _execute_with_retry(
            service.events().list(
                calendarId=calendar_id,
                privateExtendedProperty=f"{EXTERNAL_KEY_PROPERTY}={external_key}",
                showDeleted=False,
                maxResults=2,
            )
        )
    except HttpError as exc:
        raise _api_error("lookup", exc) from exc
    items = response.get("items") or []
    return items[0] if items else None


def upsert_event(
    service: Resource, calendar_id: str, event: EventInput
) -> tuple[CalendarEvent, bool]:
    """Create the event or update the one with the same key. Returns (event, created)."""
    body = event_body(event)
    existing = find_event_by_key(service, calendar_id, event.external_key)
    try:
        if existing:
            raw = _execute_with_retry(
                service.events().patch(
                    calendarId=calendar_id, eventId=existing["id"], body=body
                )
            )
            return parse_event(raw, calendar_id=calendar_id), False
        raw = _execute_with_retry(
            service.events().insert(calendarId=calendar_id, body=body)
        )
    except HttpError as exc:
        raise _api_error("write", exc) from exc
    return parse_event(raw, calendar_id=calendar_id), True


def delete_event_by_key(service: Resource, calendar_id: str, external_key: str) -> bool:
    """Delete the event written under ``external_key``. False when there was none (already gone)."""
    existing = find_event_by_key(service, calendar_id, external_key)
    if not existing:
        return False
    try:
        _execute_with_retry(
            service.events().delete(calendarId=calendar_id, eventId=existing["id"])
        )
    except HttpError as exc:
        if _status(exc) in (404, 410):
            return False
        raise _api_error("delete", exc) from exc
    return True


def list_events_between(
    service: Resource,
    calendar_id: str,
    start: datetime,
    end: datetime,
) -> list[CalendarEvent]:
    """Every event overlapping [start, end), recurring ones expanded, ordered by start."""
    if end <= start:
        raise ValueError("end must be after start.")
    return list_events(
        service,
        calendar_id=calendar_id,
        time_min=to_rfc3339(start),
        time_max=to_rfc3339(end),
        max_events=None,
    )


def free_busy(
    service: Resource,
    calendar_ids: Iterable[str],
    start: datetime,
    end: datetime,
) -> FreeBusy:
    """Busy intervals of ``calendar_ids`` in [start, end). Free events and private details are not exposed by
    Google here, only the busy time."""
    if end <= start:
        raise ValueError("end must be after start.")
    ids = list(dict.fromkeys(c for c in calendar_ids if c))
    result = FreeBusy()
    for offset in range(0, len(ids), FREEBUSY_MAX_CALENDARS):
        chunk = ids[offset : offset + FREEBUSY_MAX_CALENDARS]
        body = {
            "timeMin": to_rfc3339(start),
            "timeMax": to_rfc3339(end),
            "items": [{"id": calendar_id} for calendar_id in chunk],
        }
        try:
            response = _execute_with_retry(service.freebusy().query(body=body))
        except HttpError as exc:
            raise _api_error("free/busy", exc) from exc
        for calendar_id, data in (response.get("calendars") or {}).items():
            errors = data.get("errors") or []
            if errors:
                result.errors[calendar_id] = ", ".join(
                    str(e.get("reason") or "error") for e in errors
                )
                continue
            for interval in data.get("busy") or []:
                result.busy.append(
                    BusyInterval(
                        calendar_id=calendar_id,
                        start=_parse(interval["start"]),
                        end=_parse(interval["end"]),
                    )
                )
    result.busy.sort(key=lambda b: (b.start, b.calendar_id))
    return result


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
