"""Unified Providers factory for mail/calendar integrations."""

from .models import CalendarItem, CalendarRefItem, EmailItem
from .registry import Providers

__all__ = [
    "CalendarItem",
    "CalendarRefItem",
    "EmailItem",
    "Providers",
]

__version__ = "0.1.0"
