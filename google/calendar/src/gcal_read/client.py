"""Shared Calendar client used by the local CLI and the AWS Lambda handler."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from google_oauth.scopes import SERVICE_SCOPES
from google_oauth.secret import credentials_from_secret
from googleapiclient.discovery import Resource

from . import api as calendar_api
from . import write as calendar_write
from .auth import load_credentials, load_credentials_from_env
from .models import CalendarEvent, CalendarRef, EventInput, EventSync, FreeBusy


class CalendarClient:
    """Thin wrapper around the Google Calendar API for reading events."""

    def __init__(self, service: Resource):
        self.service = service

    @classmethod
    def from_files(
        cls,
        credentials_path: Path,
        token_path: Path,
        *,
        allow_browser: bool = True,
    ) -> CalendarClient:
        creds = load_credentials(credentials_path, token_path, allow_browser=allow_browser)
        return cls(calendar_api.build_service(creds))

    @classmethod
    def from_env(cls) -> CalendarClient:
        creds = load_credentials_from_env()
        return cls(calendar_api.build_service(creds))

    @classmethod
    def from_secret(
        cls,
        secret: Mapping[str, Any],
        *,
        write: bool = False,
        manage: bool = False,
    ) -> CalendarClient:
        """Multi-tenant / Lambda: a stored web-OAuth secret (see google_oauth.web.TokenGrant.to_secret).

        ``write=True`` also requires the event-write scope, ``manage=True`` the scopes to create and share
        calendars (both raise GoogleScopesMissingError when the connection lacks them).
        """
        required = list(SERVICE_SCOPES["calendar" if write else "calendar_readonly"])
        if manage:
            required.extend(SERVICE_SCOPES["calendar_manage"])
        creds = credentials_from_secret(secret, required_scopes=required)
        return cls(calendar_api.build_service(creds))

    def list_calendars(self) -> list[CalendarRef]:
        return calendar_api.list_calendars(self.service)

    def list_events(
        self,
        *,
        calendar_id: str = "primary",
        time_min: str | None = None,
        time_max: str | None = None,
        query: str | None = None,
        max_events: int | None = 20,
    ) -> list[CalendarEvent]:
        return calendar_api.list_events(
            self.service,
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            query=query,
            max_events=max_events,
        )

    def get(self, event_id: str, *, calendar_id: str = "primary") -> CalendarEvent:
        return calendar_api.get_event(self.service, event_id, calendar_id=calendar_id)

    def list_events_between(self, calendar_id: str, start: datetime, end: datetime) -> list[CalendarEvent]:
        return calendar_write.list_events_between(self.service, calendar_id, start, end)

    def free_busy(self, calendar_ids: Iterable[str], start: datetime, end: datetime) -> FreeBusy:
        return calendar_write.free_busy(self.service, calendar_ids, start, end)

    def upsert_event(self, calendar_id: str, event: EventInput) -> tuple[CalendarEvent, bool]:
        return calendar_write.upsert_event(self.service, calendar_id, event)

    def delete_event(self, calendar_id: str, external_key: str) -> bool:
        return calendar_write.delete_event_by_key(self.service, calendar_id, external_key)

    def create_calendar(self, summary: str, *, time_zone: str = "UTC", description: str = "") -> CalendarRef:
        return calendar_write.create_calendar(self.service, summary, time_zone=time_zone, description=description)

    def share_calendar(self, calendar_id: str, email: str, *, role: str = "reader") -> str:
        return calendar_write.share_calendar(self.service, calendar_id, email, role=role)

    def sync_events(
        self,
        calendar_id: str,
        sync_token: str | None = None,
        *,
        since: datetime | None = None,
    ) -> EventSync:
        return calendar_write.sync_events(self.service, calendar_id, sync_token, since=since)
