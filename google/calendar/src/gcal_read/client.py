"""Shared Calendar client used by the local CLI and the AWS Lambda handler."""

from __future__ import annotations

from pathlib import Path

from googleapiclient.discovery import Resource

from . import api as calendar_api
from .auth import load_credentials, load_credentials_from_env
from .models import CalendarEvent, CalendarRef


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
