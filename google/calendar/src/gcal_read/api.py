"""Google Calendar API helpers."""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from typing import Any

from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError

from .auth import CalendarAuthError
from .models import CalendarEvent, CalendarRef, EventTime

_RATE_LIMIT_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"}


def _is_rate_limit_error(exc: HttpError) -> bool:
    if getattr(exc.resp, "status", None) not in (403, 429):
        return False
    reasons = {detail.get("reason") for detail in (getattr(exc, "error_details", None) or [])}
    if reasons & _RATE_LIMIT_REASONS:
        return True
    return any(reason in str(exc) for reason in _RATE_LIMIT_REASONS)


def _execute_with_retry(request: Any, max_retries: int = 8):
    delay = 1.0
    for attempt in range(max_retries + 1):
        try:
            return request.execute()
        except HttpError as exc:
            if attempt >= max_retries or not _is_rate_limit_error(exc):
                raise
            time.sleep(delay + random.uniform(0, delay))
            delay = min(delay * 2, 60.0)


def build_service(creds) -> Resource:
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _parse_event_time(payload: dict | None) -> EventTime:
    data = payload or {}
    return EventTime(
        date=data.get("date"),
        date_time=data.get("dateTime"),
        time_zone=data.get("timeZone") or "",
    )


def parse_calendar(item: dict) -> CalendarRef:
    return CalendarRef(
        calendar_id=item.get("id") or "",
        summary=item.get("summary") or "(untitled)",
        primary=bool(item.get("primary")),
        access_role=item.get("accessRole") or "",
        time_zone=item.get("timeZone") or "",
    )


def parse_event(item: dict, *, calendar_id: str) -> CalendarEvent:
    organizer = item.get("organizer") or {}
    attendees = [
        (person.get("email") or person.get("displayName") or "").strip()
        for person in (item.get("attendees") or [])
    ]
    return CalendarEvent(
        event_id=item.get("id") or "",
        calendar_id=calendar_id,
        summary=item.get("summary") or "(no title)",
        status=item.get("status") or "",
        start=_parse_event_time(item.get("start")),
        end=_parse_event_time(item.get("end")),
        html_link=item.get("htmlLink") or "",
        location=item.get("location") or "",
        description=item.get("description"),
        organizer=organizer.get("email") or organizer.get("displayName") or "",
        attendees=[a for a in attendees if a],
        recurring_event_id=item.get("recurringEventId") or "",
    )


def list_calendars(service: Resource) -> list[CalendarRef]:
    calendars: list[CalendarRef] = []
    page_token: str | None = None
    try:
        while True:
            request_kwargs: dict[str, Any] = {"maxResults": 250}
            if page_token:
                request_kwargs["pageToken"] = page_token
            response = _execute_with_retry(service.calendarList().list(**request_kwargs))
            calendars.extend(parse_calendar(item) for item in response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except HttpError as exc:
        raise CalendarAuthError(f"Calendar list failed: {exc}") from exc
    return calendars


def list_events(
    service: Resource,
    *,
    calendar_id: str = "primary",
    time_min: str | None = None,
    time_max: str | None = None,
    query: str | None = None,
    max_events: int | None = 20,
) -> list[CalendarEvent]:
    """List events, expanding recurring instances and ordering by start time."""
    events: list[CalendarEvent] = []
    page_token: str | None = None
    if time_min is None:
        time_min = datetime.now(timezone.utc).isoformat()

    try:
        while True:
            request_kwargs: dict[str, Any] = {
                "calendarId": calendar_id,
                "singleEvents": True,
                "orderBy": "startTime",
                "timeMin": time_min,
            }
            if time_max:
                request_kwargs["timeMax"] = time_max
            if query:
                request_kwargs["q"] = query
            if page_token:
                request_kwargs["pageToken"] = page_token
            if max_events is not None:
                remaining = max_events - len(events)
                if remaining <= 0:
                    break
                request_kwargs["maxResults"] = min(250, remaining)

            response = _execute_with_retry(service.events().list(**request_kwargs))
            events.extend(parse_event(item, calendar_id=calendar_id) for item in response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except HttpError as exc:
        raise CalendarAuthError(f"Calendar events list failed: {exc}") from exc

    if max_events is not None:
        events = events[:max_events]
    return events


def get_event(service: Resource, event_id: str, *, calendar_id: str = "primary") -> CalendarEvent:
    try:
        raw = _execute_with_retry(
            service.events().get(calendarId=calendar_id, eventId=event_id)
        )
    except HttpError as exc:
        raise CalendarAuthError(f"Failed to fetch event {event_id}: {exc}") from exc
    return parse_event(raw, calendar_id=calendar_id)
