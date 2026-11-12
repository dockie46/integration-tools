"""Unified Providers factory for mail/calendar integrations."""

from .base import CalendarWriter
from .models import (
    BusyItem,
    CalendarEventItem,
    CalendarItem,
    CalendarRefItem,
    EmailItem,
    EventWrite,
    FreeBusyResult,
    WriteResult,
)
from .registry import Providers

__all__ = [
    "BusyItem",
    "CalendarEventItem",
    "CalendarItem",
    "CalendarRefItem",
    "CalendarWriter",
    "EmailItem",
    "EventWrite",
    "FreeBusyResult",
    "Providers",
    "WriteResult",
]

__version__ = "0.1.0"
