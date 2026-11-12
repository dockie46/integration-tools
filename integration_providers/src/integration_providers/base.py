"""Provider protocol and discovery hooks."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from .models import (
    CalendarEventItem,
    CalendarItem,
    CalendarRefItem,
    CalendarSyncResult,
    EmailItem,
    EventWrite,
    FreeBusyResult,
    WriteResult,
)


class Provider(Protocol):
    """One mail + calendar integration (google, icloud, …)."""

    @property
    def name(self) -> str: ...

    def read_emails(self, limit: int = 10) -> list[EmailItem]: ...

    def list_calendars(self) -> list[CalendarRefItem]: ...

    def read_calendar(
        self,
        limit: int = 10,
        *,
        calendars: list[str] | None = None,
    ) -> list[CalendarItem]: ...


class CalendarWriter(Protocol):
    """Calendar sync for apps: time-window reads in UTC, free/busy, idempotent writes by external key."""

    @property
    def name(self) -> str: ...

    def list_events_between(
        self,
        start: datetime,
        end: datetime,
        *,
        calendars: list[str] | None = None,
    ) -> list[CalendarEventItem]: ...

    def free_busy(
        self,
        start: datetime,
        end: datetime,
        *,
        calendars: list[str] | None = None,
    ) -> FreeBusyResult: ...

    def upsert_event(self, calendar_id: str, event: EventWrite) -> WriteResult: ...

    def delete_event(self, calendar_id: str, external_key: str) -> bool: ...

    def sync_events(
        self,
        calendar_id: str,
        token: str | None = None,
        *,
        since: datetime | None = None,
    ) -> CalendarSyncResult: ...

    def create_calendar(self, name: str, *, time_zone: str = "UTC", description: str = "") -> CalendarRefItem: ...

    def share_calendar(self, calendar_id: str, email: str, *, role: str = "reader") -> str: ...


class ProviderType(Protocol):
    """Class-level factory used by ``Providers.discover`` — no per-provider ifs."""

    name: str

    @classmethod
    def available(cls, root: Path) -> bool: ...

    @classmethod
    def create(cls, root: Path, *, allow_browser: bool = True) -> Provider: ...
