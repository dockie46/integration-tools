"""Typed data models for Google Calendar reads."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True, slots=True)
class CalendarRef:
    """A calendar from the user's calendar list."""

    calendar_id: str
    summary: str
    primary: bool = False
    access_role: str = ""
    time_zone: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EventTime:
    """Start or end of an event — either a date (all-day) or a dateTime."""

    date: str | None = None
    date_time: str | None = None
    time_zone: str = ""

    def display(self) -> str:
        return self.date_time or self.date or "(unknown)"

    @property
    def all_day(self) -> bool:
        return self.date_time is None and self.date is not None

    def as_utc(self, default_time_zone: str = "UTC") -> datetime | None:
        """The moment in UTC. An all-day date starts at midnight in ``time_zone`` (or ``default_time_zone``)."""
        if self.date_time:
            moment = datetime.fromisoformat(self.date_time.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=_zone(self.time_zone or default_time_zone))
            return moment.astimezone(UTC)
        if self.date:
            day = datetime.fromisoformat(self.date).date()
            return datetime.combine(day, time.min, _zone(self.time_zone or default_time_zone)).astimezone(UTC)
        return None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class CalendarEvent:
    """A calendar event suitable for CLI or Lambda output."""

    event_id: str
    calendar_id: str
    summary: str
    status: str
    start: EventTime
    end: EventTime
    html_link: str = ""
    location: str = ""
    description: str | None = None
    organizer: str = ""
    attendees: list[str] = field(default_factory=list)
    recurring_event_id: str = ""
    transparency: str = "opaque"
    external_key: str = ""

    @property
    def busy(self) -> bool:
        """Blocks time (Google 'Busy'); 'Free' events and cancelled ones do not."""
        return self.transparency != "transparent" and self.status != "cancelled"

    def to_dict(self) -> dict:
        return asdict(self)


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


@dataclass(frozen=True, slots=True)
class EventInput:
    """An event to write. ``external_key`` (e.g. a booking id) makes writes idempotent: the same key
    always updates the same event. Times must be timezone-aware; ``time_zone`` is how Google shows them."""

    summary: str
    start: datetime
    end: datetime
    external_key: str
    description: str = ""
    location: str = ""
    time_zone: str = "UTC"
    busy: bool = True

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("EventInput times must be timezone-aware.")
        if self.end <= self.start:
            raise ValueError("EventInput must end after it starts.")
        if not self.external_key.strip():
            raise ValueError("EventInput needs an external_key.")


@dataclass(frozen=True, slots=True)
class BusyInterval:
    calendar_id: str
    start: datetime
    end: datetime

    def to_dict(self) -> dict:
        return {"calendar_id": self.calendar_id, "start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass(slots=True)
class FreeBusy:
    """Busy time per calendar; ``errors`` names calendars Google could not answer for (no access, not found)."""

    busy: list[BusyInterval] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    def for_calendar(self, calendar_id: str) -> list[BusyInterval]:
        return [b for b in self.busy if b.calendar_id == calendar_id]


@dataclass(slots=True)
class EventSync:
    """One incremental sync step. ``full`` means Google dropped the old token and this is a fresh full read:
    the caller should replace what it holds for the calendar instead of merging."""

    changed: list[CalendarEvent] = field(default_factory=list)
    deleted_ids: list[str] = field(default_factory=list)
    next_sync_token: str = ""
    full: bool = False
