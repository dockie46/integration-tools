"""Unified provider models — provider-agnostic mail and calendar items."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class EmailItem:
    provider: str
    id: str
    subject: str
    sender: str
    date: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CalendarRefItem:
    """A calendar belonging to a provider (for discovery / config)."""

    provider: str
    id: str
    name: str
    primary: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CalendarItem:
    provider: str
    id: str
    summary: str
    start: str
    end: str = ""
    calendar: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CalendarEventItem:
    """An event in a time window, times in UTC (for availability and displays)."""

    provider: str
    id: str
    calendar: str
    summary: str
    start: datetime
    end: datetime
    all_day: bool = False
    location: str = ""
    busy: bool = True
    external_key: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["start"] = self.start.isoformat()
        data["end"] = self.end.isoformat()
        return data


@dataclass(frozen=True, slots=True)
class BusyItem:
    provider: str
    calendar: str
    start: datetime
    end: datetime

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "calendar": self.calendar,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }


@dataclass(slots=True)
class FreeBusyResult:
    """Busy time across calendars; ``errors`` maps calendars that could not be read to the reason."""

    items: list[BusyItem] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"items": [i.to_dict() for i in self.items], "errors": dict(self.errors)}


@dataclass(frozen=True, slots=True)
class EventWrite:
    """A provider-agnostic event to create or update. ``external_key`` (e.g. a booking id) identifies it:
    writing the same key again updates the same event. Times must be timezone-aware."""

    summary: str
    start: datetime
    end: datetime
    external_key: str
    description: str = ""
    location: str = ""
    time_zone: str = "UTC"
    busy: bool = True


@dataclass(frozen=True, slots=True)
class WriteResult:
    provider: str
    calendar: str
    event_id: str
    created: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class CalendarSyncResult:
    """Changes in one calendar since the last token. ``full``: the provider started over, so replace what is
    held for this calendar instead of merging. Store ``next_token`` for the next call."""

    provider: str
    calendar: str
    changed: list[CalendarEventItem] = field(default_factory=list)
    deleted_ids: list[str] = field(default_factory=list)
    next_token: str = ""
    full: bool = False

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "calendar": self.calendar,
            "changed": [e.to_dict() for e in self.changed],
            "deleted_ids": list(self.deleted_ids),
            "next_token": self.next_token,
            "full": self.full,
        }
