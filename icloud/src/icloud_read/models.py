"""Typed models for iCloud mail and calendar reads."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class MailMessage:
    uid: str
    subject: str
    sender: str
    date: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CalendarRef:
    """A calendar available on the iCloud account."""

    calendar_id: str
    summary: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    uid: str
    summary: str
    start: str
    end: str
    calendar: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
