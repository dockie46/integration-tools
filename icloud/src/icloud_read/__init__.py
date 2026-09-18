"""Read iCloud Mail (IMAP) and Calendar (CalDAV)."""

from .auth import CredentialsMissingError, ICloudAuthError, load_credentials
from .calendar_client import ICloudCalendarClient
from .mail_client import ICloudMailClient
from .models import CalendarEvent, CalendarRef, MailMessage

__all__ = [
    "CalendarEvent",
    "CalendarRef",
    "CredentialsMissingError",
    "ICloudAuthError",
    "ICloudCalendarClient",
    "ICloudMailClient",
    "MailMessage",
    "load_credentials",
]

__version__ = "0.1.0"
