"""Graph calendar reads: rooms, a time window (calendarView) and event parsing."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from .graph import GraphClient
from .models import CalendarEvent, EventTime, RoomRef

# Private extended property carrying EventInput.external_key (e.g. a booking id); only this app reads it.
# The GUID namespaces the property so it never clashes with another add-in's "sourceKey".
SOURCE_KEY_GUID = "a1e7c5d2-6b3f-4c8a-9e2d-7f0b1c4a5d6e"
EXTERNAL_KEY_PROP = f"String {{{SOURCE_KEY_GUID}}} Name sourceKey"
EXPAND_EXTERNAL_KEY = f"singleValueExtendedProperties($filter=id eq '{EXTERNAL_KEY_PROP}')"

# Fields we parse; keeps the payload small and predictable.
EVENT_SELECT = "id,subject,start,end,isAllDay,isCancelled,showAs,location,organizer,type"

# Reads ask Graph to express all times in UTC.
PREFER_UTC = 'outlook.timezone="UTC"'

_PAGE_SIZE = 100


def to_graph_time(moment: datetime) -> str:
    """A UTC ISO 8601 instant for startDateTime / endDateTime query params."""
    if moment.tzinfo is None:
        raise ValueError("Calendar times must be timezone-aware.")
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _mailbox_path(calendar_id: str, suffix: str) -> str:
    return f"users/{quote(calendar_id, safe='@._-')}/{suffix}"


def _external_key(item: Mapping[str, Any]) -> str:
    for prop in item.get("singleValueExtendedProperties") or []:
        if str(prop.get("id") or "") == EXTERNAL_KEY_PROP:
            return str(prop.get("value") or "")
    return ""


def _event_time(payload: Mapping[str, Any] | None, *, all_day: bool) -> EventTime:
    data = payload or {}
    return EventTime(
        date_time=data.get("dateTime"),
        time_zone=str(data.get("timeZone") or ""),
        all_day=all_day,
    )


def parse_event(item: Mapping[str, Any], *, calendar_id: str) -> CalendarEvent:
    organizer = ((item.get("organizer") or {}).get("emailAddress") or {})
    location = (item.get("location") or {}).get("displayName") or ""
    all_day = bool(item.get("isAllDay"))
    return CalendarEvent(
        event_id=str(item.get("id") or ""),
        calendar_id=calendar_id,
        subject=str(item.get("subject") or "(no title)"),
        start=_event_time(item.get("start"), all_day=all_day),
        end=_event_time(item.get("end"), all_day=all_day),
        is_all_day=all_day,
        is_cancelled=bool(item.get("isCancelled")),
        show_as=str(item.get("showAs") or "busy"),
        location=location,
        organizer=str(organizer.get("address") or organizer.get("name") or ""),
        external_key=_external_key(item),
    )


def parse_room(item: Mapping[str, Any]) -> RoomRef:
    return RoomRef(
        email=str(item.get("emailAddress") or ""),
        name=str(item.get("displayName") or item.get("emailAddress") or "(room)"),
    )


def list_rooms(graph: GraphClient) -> list[RoomRef]:
    """Room mailboxes of the tenant (needs Place.Read.All). Rooms without an e-mail are skipped."""
    rooms: list[RoomRef] = []
    response = graph.get("places/microsoft.graph.room", params={"$top": _PAGE_SIZE})
    while True:
        rooms.extend(parse_room(item) for item in response.get("value", []))
        nxt = response.get("@odata.nextLink")
        if not nxt:
            break
        response = graph.get_url(nxt)
    return [room for room in rooms if room.email]


def calendar_view(
    graph: GraphClient,
    calendar_id: str,
    start: datetime,
    end: datetime,
) -> list[CalendarEvent]:
    """Every event overlapping [start, end) in the room's calendar, recurring series expanded to occurrences."""
    if end <= start:
        raise ValueError("end must be after start.")
    params = {
        "startDateTime": to_graph_time(start),
        "endDateTime": to_graph_time(end),
        "$top": _PAGE_SIZE,
        "$select": EVENT_SELECT,
        "$expand": EXPAND_EXTERNAL_KEY,
    }
    events: list[CalendarEvent] = []
    response = graph.get(_mailbox_path(calendar_id, "calendarView"), params=params, prefer=PREFER_UTC)
    while True:
        events.extend(parse_event(item, calendar_id=calendar_id) for item in response.get("value", []))
        nxt = response.get("@odata.nextLink")
        if not nxt:
            break
        response = graph.get_url(nxt, prefer=PREFER_UTC)
    return events


def get_event(graph: GraphClient, calendar_id: str, event_id: str) -> CalendarEvent:
    params = {"$select": EVENT_SELECT, "$expand": EXPAND_EXTERNAL_KEY}
    item = graph.get(_mailbox_path(calendar_id, f"events/{quote(event_id, safe='')}"), params=params, prefer=PREFER_UTC)
    return parse_event(item, calendar_id=calendar_id)
