"""iCloud Calendar via CalDAV."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import caldav
from caldav.lib.error import AuthorizationError, DAVError

from .auth import ICloudAuthError, ICloudCredentials, load_credentials
from .models import CalendarEvent, CalendarRef

CALDAV_URL = "https://caldav.icloud.com/"


def _format_dt(value: date | datetime | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return value.isoformat()


def _event_start(component) -> date | datetime | None:
    if component is None or not hasattr(component, "get"):
        return None
    dtstart = component.get("dtstart")
    return dtstart.dt if dtstart is not None else None


def _event_end(component) -> date | datetime | None:
    if component is None or not hasattr(component, "get"):
        return None
    dtend = component.get("dtend")
    if dtend is not None:
        return dtend.dt
    duration = component.get("duration")
    start = _event_start(component)
    if duration is not None and start is not None and isinstance(start, datetime):
        return start + duration.dt
    return None


def _sort_key(event: CalendarEvent) -> str:
    return event.start or ""


def _calendar_name(calendar) -> str:
    try:
        return str(calendar.get_display_name() or "").strip()
    except Exception:
        return str(getattr(calendar, "name", "") or "").strip()


def _calendar_id(calendar) -> str:
    url = getattr(calendar, "url", None)
    return str(url) if url is not None else _calendar_name(calendar)


class ICloudCalendarClient:
    """Thin CalDAV wrapper for reading iCloud Calendar events."""

    def __init__(self, credentials: ICloudCredentials):
        self._credentials = credentials

    @classmethod
    def from_file(cls, path: Path) -> ICloudCalendarClient:
        return cls(load_credentials(path))

    def _connect(self):
        try:
            client = caldav.DAVClient(
                url=CALDAV_URL,
                username=self._credentials.email,
                password=self._credentials.password,
            )
            return client.principal()
        except AuthorizationError as exc:
            raise ICloudAuthError(
                "iCloud Calendar login failed. Check email and app-specific password."
            ) from exc
        except DAVError as exc:
            raise ICloudAuthError(f"iCloud Calendar connection failed: {exc}") from exc

    def list_calendars(self) -> list[CalendarRef]:
        principal = self._connect()
        try:
            calendars = principal.calendars()
        except DAVError as exc:
            raise ICloudAuthError(f"iCloud Calendar list failed: {exc}") from exc
        return [
            CalendarRef(calendar_id=_calendar_id(cal), summary=_calendar_name(cal) or "(unnamed)")
            for cal in calendars
        ]

    def list_events(
        self,
        max_events: int = 10,
        *,
        days_ahead: int = 90,
        calendar_names: list[str] | tuple[str, ...] | None = None,
    ) -> list[CalendarEvent]:
        if max_events <= 0:
            return []

        selected = calendar_names if calendar_names is not None else self._credentials.calendars
        allow = {name.casefold() for name in selected} if selected else None

        principal = self._connect()
        try:
            calendars = principal.calendars()
        except DAVError as exc:
            raise ICloudAuthError(f"iCloud Calendar list failed: {exc}") from exc

        start = datetime.now(timezone.utc)
        end = start + timedelta(days=days_ahead)
        collected: list[CalendarEvent] = []

        try:
            for calendar in calendars:
                cal_name = _calendar_name(calendar)
                if allow is not None and cal_name.casefold() not in allow:
                    continue

                try:
                    results = calendar.date_search(start=start, end=end, expand=True)
                except DAVError:
                    continue

                for item in results:
                    try:
                        component = item.icalendar_component
                    except Exception:
                        continue
                    if component is None:
                        continue
                    if str(component.name).upper() != "VEVENT":
                        try:
                            vevents = component.walk("VEVENT")
                        except Exception:
                            continue
                    else:
                        vevents = [component]

                    for vevent in vevents:
                        summary = vevent.get("summary")
                        uid = vevent.get("uid")
                        collected.append(
                            CalendarEvent(
                                uid=str(uid) if uid is not None else "",
                                summary=str(summary) if summary is not None else "(no title)",
                                start=_format_dt(_event_start(vevent)),
                                end=_format_dt(_event_end(vevent)),
                                calendar=cal_name,
                            )
                        )
        except DAVError as exc:
            raise ICloudAuthError(f"iCloud Calendar read failed: {exc}") from exc

        collected.sort(key=_sort_key)
        return collected[:max_events]
