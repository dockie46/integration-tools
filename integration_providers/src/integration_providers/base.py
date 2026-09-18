"""Provider protocol and discovery hooks."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import CalendarItem, CalendarRefItem, EmailItem


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


class ProviderType(Protocol):
    """Class-level factory used by ``Providers.discover`` — no per-provider ifs."""

    name: str

    @classmethod
    def available(cls, root: Path) -> bool: ...

    @classmethod
    def create(cls, root: Path, *, allow_browser: bool = True) -> Provider: ...
