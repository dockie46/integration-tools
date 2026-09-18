"""Typed data models for Google Calendar reads."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


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

    def to_dict(self) -> dict:
        return asdict(self)
