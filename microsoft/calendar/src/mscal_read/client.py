"""Shared Microsoft 365 calendar client used by the provider adapter and (locally) tests.

Auth is app-only: a stored connection secret with ``tenantId`` / ``clientId`` / ``clientSecret`` (an Entra ID
app registration with admin consent). Room mailboxes are addressed by e-mail.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from . import api as calendar_api
from . import write as calendar_write
from .auth import AppCredentials, AppOnlyToken
from .graph import GraphClient
from .models import CalendarEvent, EventInput, EventSync, FreeBusy, RoomRef


class CalendarClient:
    """Thin wrapper over Microsoft Graph for reading and writing room calendars."""

    def __init__(self, graph: GraphClient) -> None:
        self.graph = graph

    @classmethod
    def from_secret(cls, secret: Mapping[str, Any], *, session: Any | None = None) -> CalendarClient:
        """One tenant's Microsoft 365 account from its stored app-registration secret (no files, no browser)."""
        import requests

        from .graph import RequestsTransport

        credentials = AppCredentials.from_secret(secret)
        http = session or requests.Session()
        token = AppOnlyToken(credentials, http)
        return cls(GraphClient(RequestsTransport(token, http)))

    def list_rooms(self) -> list[RoomRef]:
        return calendar_api.list_rooms(self.graph)

    def list_events_between(self, calendar_id: str, start: datetime, end: datetime) -> list[CalendarEvent]:
        return calendar_api.calendar_view(self.graph, calendar_id, start, end)

    def get(self, event_id: str, *, calendar_id: str) -> CalendarEvent:
        return calendar_api.get_event(self.graph, calendar_id, event_id)

    def free_busy(self, calendar_ids: Iterable[str], start: datetime, end: datetime) -> FreeBusy:
        return calendar_write.free_busy(self.graph, calendar_ids, start, end)

    def upsert_event(self, calendar_id: str, event: EventInput) -> tuple[CalendarEvent, bool]:
        return calendar_write.upsert_event(self.graph, calendar_id, event)

    def delete_event(self, calendar_id: str, external_key: str) -> bool:
        return calendar_write.delete_event_by_key(self.graph, calendar_id, external_key)

    def decline_event(self, calendar_id: str, event_id: str, comment: str = "") -> bool:
        return calendar_write.decline_event(self.graph, calendar_id, event_id, comment)

    def sync_events(
        self,
        calendar_id: str,
        sync_token: str | None = None,
        *,
        since: datetime | None = None,
    ) -> EventSync:
        return calendar_write.sync_events(self.graph, calendar_id, sync_token, since=since)
