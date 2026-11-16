"""Microsoft 365 (Graph) calendar reads, writes and delta sync for room mailboxes (app-only)."""

from .auth import (
    AppCredentials,
    AppOnlyToken,
    MicrosoftAuthError,
    MicrosoftCredentialsError,
)
from .client import CalendarClient
from .graph import GraphApiError, GraphAuthError, GraphClient, RequestsTransport
from .models import (
    BusyInterval,
    CalendarEvent,
    EventInput,
    EventSync,
    EventTime,
    FreeBusy,
    RoomRef,
)

__all__ = [
    "AppCredentials",
    "AppOnlyToken",
    "BusyInterval",
    "CalendarClient",
    "CalendarEvent",
    "EventInput",
    "EventSync",
    "EventTime",
    "FreeBusy",
    "GraphApiError",
    "GraphAuthError",
    "GraphClient",
    "MicrosoftAuthError",
    "MicrosoftCredentialsError",
    "RequestsTransport",
    "RoomRef",
]
