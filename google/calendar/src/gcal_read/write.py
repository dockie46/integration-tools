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

from .api import (
    EXTERNAL_KEY_PROPERTY,
    _execute_with_retry,
    list_events,
    parse_calendar,
    parse_event,
)
from .models import (
    BusyInterval,
    CalendarEvent,
    CalendarRef,
    EventInput,
    EventSync,
    FreeBusy,
)

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


def create_calendar(
    service: Resource,
    summary: str,
    *,
    time_zone: str = "UTC",
    description: str = "",
) -> CalendarRef:
    """A new secondary calendar owned by the connected account (e.g. one per meeting room)."""
    if not summary.strip():
        raise ValueError("A calendar needs a name.")
    body = {
        "summary": summary.strip(),
        "timeZone": time_zone,
        "description": description,
    }
    try:
        raw = _execute_with_retry(service.calendars().insert(body=body))
    except HttpError as exc:
        raise _api_error("create", exc) from exc
    ref = parse_calendar(raw)
    return CalendarRef(
        calendar_id=ref.calendar_id,
        summary=ref.summary,
        primary=False,
        access_role="owner",
        time_zone=ref.time_zone or time_zone,
    )


ACL_ROLES = ("freeBusyReader", "reader", "writer", "owner")


def share_calendar(
    service: Resource, calendar_id: str, email: str, *, role: str = "reader"
) -> str:
    """Give one person (or a group address) access to a calendar. Returns the ACL rule id."""
    if role not in ACL_ROLES:
        raise ValueError(
            f"Unknown calendar role {role!r}. Use one of: {', '.join(ACL_ROLES)}"
        )
    body = {"role": role, "scope": {"type": "user", "value": email}}
    try:
        raw = _execute_with_retry(
            service.acl().insert(
                calendarId=calendar_id, body=body, sendNotifications=False
            )
        )
    except HttpError as exc:
        raise _api_error("share", exc) from exc
    return str(raw.get("id") or "")


def sync_events(
    service: Resource,
    calendar_id: str,
    sync_token: str | None = None,
    *,
    since: datetime | None = None,
) -> EventSync:
    """Changes since ``sync_token`` (recurring events expanded). Without a token, or when Google answers 410
    because the token expired, it reads everything from ``since`` (default: no limit) and sets ``full``.
    Store ``next_sync_token`` for the next call."""
    if sync_token:
        try:
            return _sync_pages(
                service, calendar_id, {"syncToken": sync_token}, full=False
            )
        except HttpError as exc:
            if _status(exc) != 410:
                raise _api_error("sync", exc) from exc
    base: dict[str, Any] = {}
    if since is not None:
        base["timeMin"] = to_rfc3339(since)
    try:
        return _sync_pages(service, calendar_id, base, full=True)
    except HttpError as exc:
        raise _api_error("sync", exc) from exc


def _sync_pages(
    service: Resource, calendar_id: str, base: dict[str, Any], *, full: bool
) -> EventSync:
    result = EventSync(full=full)
    page_token: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "calendarId": calendar_id,
            "singleEvents": True,
            "maxResults": 250,
            **base,
        }
        if not full:
            kwargs["showDeleted"] = True
        if page_token:
            kwargs["pageToken"] = page_token
        response = _execute_with_retry(service.events().list(**kwargs))
        for item in response.get("items", []):
            if item.get("status") == "cancelled":
                result.deleted_ids.append(str(item.get("id") or ""))
            else:
                result.changed.append(parse_event(item, calendar_id=calendar_id))
        page_token = response.get("nextPageToken")
        if not page_token:
            result.next_sync_token = str(response.get("nextSyncToken") or "")
            return result


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
