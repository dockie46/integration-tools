"""Unified provider models — provider-agnostic mail and calendar items."""

from __future__ import annotations

from dataclasses import asdict, dataclass


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
