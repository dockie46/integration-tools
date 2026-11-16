"""Typed data models for Microsoft 365 (Graph) calendar reads and writes.

Mirrors the Google models (``gcal_read.models``) so the provider adapters stay symmetric: the same
``EventInput`` / ``EventSync`` / ``FreeBusy`` shapes map onto the provider-agnostic items.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def normalize_iso(raw: str) -> str:
    """Graph returns up to 7 fractional-second digits; ``datetime.fromisoformat`` (3.11) takes at most 6."""
    value = raw.replace("Z", "+00:00")
    dot = value.find(".")
    if dot == -1:
        return value
    tail_start = dot + 1
    while tail_start < len(value) and value[tail_start].isdigit():
        tail_start += 1
    digits = value[dot + 1 : tail_start]
    if len(digits) <= 6:
        return value
    return value[:dot] + "." + digits[:6] + value[tail_start:]


@dataclass(frozen=True, slots=True)
class RoomRef:
    """A room mailbox (``/places/microsoft.graph.room``). The e-mail address is the calendar id we address."""

    email: str
    name: str
    time_zone: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EventTime:
    """Graph ``dateTimeTimeZone``: a naive ``dateTime`` plus the zone it is expressed in.

    Reads ask for ``Prefer: outlook.timezone="UTC"``, so ``time_zone`` is normally ``UTC``; all-day events still
    come back at local midnight, so the zone is honoured when converting.
    """

    date_time: str | None = None
    time_zone: str = ""
    all_day: bool = False

    def display(self) -> str:
        return self.date_time or "(unknown)"

    def as_utc(self, default_time_zone: str = "UTC") -> datetime | None:
        """The moment in UTC. An all-day event starts at midnight in ``time_zone`` (or ``default_time_zone``)."""
        if not self.date_time:
            return None
        moment = datetime.fromisoformat(normalize_iso(self.date_time))
        if self.all_day:
            moment = datetime.combine(moment.date(), time.min)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=_zone(self.time_zone or default_time_zone))
        return moment.astimezone(UTC)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class CalendarEvent:
    """A Graph event suitable for availability and displays."""

    event_id: str
    calendar_id: str
    subject: str
    start: EventTime
    end: EventTime
    is_all_day: bool = False
    is_cancelled: bool = False
    show_as: str = "busy"
    location: str = ""
    organizer: str = ""
    external_key: str = ""

    @property
    def summary(self) -> str:
        return self.subject

    @property
    def busy(self) -> bool:
        """Blocks time. Graph 'free' (and cancelled occurrences) do not; busy/tentative/oof/workingElsewhere do."""
        return self.show_as.lower() != "free" and not self.is_cancelled

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EventInput:
    """An event to write. ``external_key`` (e.g. a booking id) makes writes idempotent: the same key always
    updates the same event. Times must be timezone-aware; ``time_zone`` is how Outlook shows them."""

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
    """Busy time per calendar; ``errors`` names calendars Graph could not answer for (no access, not found)."""

    busy: list[BusyInterval] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    def for_calendar(self, calendar_id: str) -> list[BusyInterval]:
        return [b for b in self.busy if b.calendar_id == calendar_id]


@dataclass(slots=True)
class EventSync:
    """One incremental delta step. ``full`` means Graph had no usable delta token (none given or it expired):
    this is a fresh read over the whole window, so the caller replaces what it holds instead of merging.
    ``next_token`` is the opaque delta link to pass back next time."""

    changed: list[CalendarEvent] = field(default_factory=list)
    deleted_ids: list[str] = field(default_factory=list)
    next_token: str = ""
    full: bool = False
