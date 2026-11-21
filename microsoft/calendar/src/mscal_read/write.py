"""Graph calendar writes, free/busy and delta sync for apps that keep their own records.

Every written event carries ``EventInput.external_key`` in a private single-value extended property, so the app
finds, updates and deletes "its" event without storing Graph's event id (and a retry never duplicates it).
Room mailboxes are addressed by e-mail as ``/users/{roomEmail}``; app-only access is scoped to them tenant-side.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .api import (
    EVENT_SELECT,
    EXPAND_EXTERNAL_KEY,
    EXTERNAL_KEY_PROP,
    PREFER_UTC,
    _mailbox_path,
    parse_event,
    to_graph_time,
)
from .graph import GraphApiError, GraphClient
from .models import (
    BusyInterval,
    CalendarEvent,
    EventInput,
    EventSync,
    FreeBusy,
    normalize_iso,
)

# Graph requires a bounded window for a delta; a fresh sync covers this far ahead of ``since``.
DEFAULT_HORIZON_DAYS = 400

# Graph showAs values that block time (everything but "free"); "unknown" is treated as busy, to be safe.
_FREE = "free"

_BUSY_STATUSES = {"busy", "tentative", "oof", "workingelsewhere", "unknown"}


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _local_wall_time(moment: datetime, time_zone: str) -> str:
    """Wall-clock time in ``time_zone`` with no offset — how Graph wants a dateTime alongside its timeZone."""
    local = moment.astimezone(_zone(time_zone))
    return local.replace(tzinfo=None).isoformat()


def event_body(event: EventInput) -> dict:
    """Graph event resource for ``event``. Times are sent in ``event.time_zone`` so Outlook shows them local."""
    return {
        "subject": event.summary,
        "body": {"contentType": "text", "content": event.description},
        "location": {"displayName": event.location},
        "start": {"dateTime": _local_wall_time(event.start, event.time_zone), "timeZone": event.time_zone},
        "end": {"dateTime": _local_wall_time(event.end, event.time_zone), "timeZone": event.time_zone},
        "showAs": "busy" if event.busy else "free",
        "singleValueExtendedProperties": [{"id": EXTERNAL_KEY_PROP, "value": event.external_key}],
    }


def find_event_by_key(graph: GraphClient, calendar_id: str, external_key: str) -> dict | None:
    """The live event this app wrote under ``external_key``, or None."""
    escaped = external_key.replace("'", "''")
    params = {
        "$filter": (
            f"singleValueExtendedProperties/any(ep: ep/id eq '{EXTERNAL_KEY_PROP}' and ep/value eq '{escaped}')"
        ),
        "$top": 2,
        "$select": EVENT_SELECT,
        "$expand": EXPAND_EXTERNAL_KEY,
    }
    response = graph.get(_mailbox_path(calendar_id, "calendar/events"), params=params, prefer=PREFER_UTC)
    items = response.get("value") or []
    return items[0] if items else None


def upsert_event(graph: GraphClient, calendar_id: str, event: EventInput) -> tuple[CalendarEvent, bool]:
    """Create the event or update the one with the same key. Returns (event, created)."""
    body = event_body(event)
    existing = find_event_by_key(graph, calendar_id, event.external_key)
    if existing:
        raw = graph.patch(_mailbox_path(calendar_id, f"events/{existing['id']}"), body)
        return parse_event(raw, calendar_id=calendar_id), False
    raw = graph.post(_mailbox_path(calendar_id, "calendar/events"), body)
    return parse_event(raw, calendar_id=calendar_id), True


def delete_event_by_key(graph: GraphClient, calendar_id: str, external_key: str) -> bool:
    """Delete the event written under ``external_key``. False when there was none (already gone)."""
    existing = find_event_by_key(graph, calendar_id, external_key)
    if not existing:
        return False
    try:
        graph.delete(_mailbox_path(calendar_id, f"events/{existing['id']}"))
    except GraphApiError as exc:
        if exc.status in (404, 410):
            return False
        raise
    return True



def decline_event(graph: GraphClient, calendar_id: str, event_id: str, comment: str = "") -> bool:
    """Decline ``event_id`` in the mailbox ``calendar_id`` (a room) and send the organizer the answer.

    False when the event is gone (404 / 410); a second decline of the same event is accepted by Graph."""
    body = {"comment": comment, "sendResponse": True}
    try:
        graph.post(_mailbox_path(calendar_id, f"events/{event_id}/decline"), body)
    except GraphApiError as exc:
        if exc.status in (404, 410):
            return False
        raise
    return True


def free_busy(graph: GraphClient, calendar_ids: Iterable[str], start: datetime, end: datetime) -> FreeBusy:
    """Busy intervals of ``calendar_ids`` in [start, end) via getSchedule. Only busy time is exposed, no titles."""
    if end <= start:
        raise ValueError("end must be after start.")
    ids = list(dict.fromkeys(c for c in calendar_ids if c))
    result = FreeBusy()
    if not ids:
        return result

    body = {
        "schedules": ids,
        "startTime": {"dateTime": _utc_naive(start), "timeZone": "UTC"},
        "endTime": {"dateTime": _utc_naive(end), "timeZone": "UTC"},
        "availabilityViewInterval": 30,
    }
    response = graph.post(_mailbox_path(ids[0], "calendar/getSchedule"), body)
    for entry in response.get("value", []):
        schedule_id = str(entry.get("scheduleId") or "")
        error = entry.get("error")
        if error:
            message = error.get("message") if isinstance(error, dict) else str(error)
            result.errors[schedule_id] = str(message or "error")
            continue
        for slot in entry.get("scheduleItems") or []:
            if str(slot.get("status") or "").lower() not in _BUSY_STATUSES:
                continue
            result.busy.append(
                BusyInterval(
                    calendar_id=schedule_id,
                    start=_parse(slot.get("start")),
                    end=_parse(slot.get("end")),
                )
            )
    result.busy.sort(key=lambda b: (b.start, b.calendar_id))
    return result


def sync_events(
    graph: GraphClient,
    calendar_id: str,
    sync_token: str | None = None,
    *,
    since: datetime | None = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> EventSync:
    """Changes since ``sync_token`` (an opaque delta link). Without one, or when Graph answers 410 because the
    token expired, reads the whole window [since, since+horizon] afresh and sets ``full``. Recurring series come
    as their single occurrences. Store ``next_token`` for the next call."""
    if sync_token:
        try:
            return _delta_pages(graph, graph.get_url(sync_token, prefer=PREFER_UTC), calendar_id, full=False)
        except GraphApiError as exc:
            if exc.status != 410:
                raise
    start = since or datetime.now(UTC)
    end = start + timedelta(days=max(1, horizon_days))
    params = {
        "startDateTime": to_graph_time(start),
        "endDateTime": to_graph_time(end),
        "$select": EVENT_SELECT,
        "$expand": EXPAND_EXTERNAL_KEY,
    }
    first = graph.get(_mailbox_path(calendar_id, "calendarView/delta"), params=params, prefer=PREFER_UTC)
    return _delta_pages(graph, first, calendar_id, full=True)


def _delta_pages(graph: GraphClient, response: dict, calendar_id: str, *, full: bool) -> EventSync:
    result = EventSync(full=full)
    while True:
        for item in response.get("value", []):
            if "@removed" in item:
                result.deleted_ids.append(str(item.get("id") or ""))
            else:
                result.changed.append(parse_event(item, calendar_id=calendar_id))
        nxt = response.get("@odata.nextLink")
        if nxt:
            response = graph.get_url(nxt, prefer=PREFER_UTC)
            continue
        result.next_token = str(response.get("@odata.deltaLink") or "")
        return result


def _utc_naive(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("Calendar times must be timezone-aware.")
    return moment.astimezone(UTC).replace(tzinfo=None).isoformat()


def _parse(payload: dict | None) -> datetime:
    data = payload or {}
    moment = datetime.fromisoformat(normalize_iso(str(data.get("dateTime") or "")))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_zone(str(data.get("timeZone") or "UTC")))
    return moment.astimezone(UTC)
