"""Google provider adapter."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from gcal_read.client import CalendarClient
from gcal_read.models import EventInput
from gmail_read.client import GmailClient

from .models import (
    BusyItem,
    CalendarEventItem,
    CalendarItem,
    CalendarRefItem,
    CalendarSyncResult,
    EmailItem,
    EventWrite,
    FreeBusyResult,
    WriteResult,
)


def _env_token_present() -> bool:
    return bool(
        (os.environ.get("GOOGLE_TOKEN_JSON") or "").strip()
        or (os.environ.get("GMAIL_TOKEN_JSON") or "").strip()
        or (os.environ.get("GOOGLE_TOKEN_PATH") or "").strip()
        or (os.environ.get("GMAIL_TOKEN_PATH") or "").strip()
    )


def _load_calendar_ids(settings_path: Path | None = None) -> tuple[str, ...]:
    """Optional credentials/google.json or GOOGLE_CALENDARS env (comma-separated ids)."""
    raw_env = (os.environ.get("GOOGLE_CALENDARS") or "").strip()
    if raw_env:
        ids = tuple(part.strip() for part in raw_env.split(",") if part.strip())
        if ids:
            return ids

    if settings_path is None or not settings_path.exists():
        return ("primary",)
    try:
        data = json.loads(settings_path.read_text())
    except json.JSONDecodeError:
        return ("primary",)
    raw = data.get("calendars")
    if not isinstance(raw, list) or not raw:
        return ("primary",)
    ids = tuple(str(item).strip() for item in raw if str(item).strip())
    return ids or ("primary",)


def _secret_calendar_ids(secret: Mapping[str, Any]) -> tuple[str, ...]:
    raw = next((v for k, v in secret.items() if str(k).lower() == "calendars"), None)
    if isinstance(raw, list | tuple):
        ids = tuple(str(item).strip() for item in raw if str(item).strip())
    elif raw:
        ids = tuple(part.strip() for part in str(raw).split(",") if part.strip())
    else:
        ids = ()
    return ids or ("primary",)


class GoogleProvider:
    name = "google"

    def __init__(
        self,
        credentials_path: Path | None = None,
        token_path: Path | None = None,
        *,
        allow_browser: bool = True,
        use_env: bool = False,
        calendar_ids: tuple[str, ...] = ("primary",),
        secret: Mapping[str, Any] | None = None,
    ) -> None:
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._allow_browser = allow_browser
        self._use_env = use_env
        self._secret = dict(secret) if secret is not None else None
        self._calendar_ids = calendar_ids
        self._gmail: GmailClient | None = None
        self._calendar: CalendarClient | None = None
        self._calendar_writer: CalendarClient | None = None
        self._calendar_manager: CalendarClient | None = None

    @classmethod
    def available(cls, root: Path) -> bool:
        if (root / "credentials" / "credentials.json").exists():
            return True
        return _env_token_present()

    @classmethod
    def create(cls, root: Path, *, allow_browser: bool = True) -> GoogleProvider:
        creds = root / "credentials" / "credentials.json"
        token = root / "token.json"
        calendar_ids = _load_calendar_ids(root / "credentials" / "google.json")
        if creds.exists():
            return cls(
                creds,
                token,
                allow_browser=allow_browser,
                calendar_ids=calendar_ids,
            )
        return cls(use_env=True, allow_browser=False, calendar_ids=calendar_ids)

    @classmethod
    def from_secret(
        cls,
        secret: Mapping[str, Any],
        *,
        calendar_ids: tuple[str, ...] | list[str] | None = None,
    ) -> GoogleProvider:
        """One tenant's Google account from its stored web-OAuth secret (no files, no browser).

        Calendar ids come from ``calendar_ids``, else the secret's ``calendars`` (list or comma-separated),
        else ``primary``.
        """
        ids = tuple(calendar_ids) if calendar_ids else _secret_calendar_ids(secret)
        return cls(allow_browser=False, calendar_ids=ids, secret=secret)

    def _mail(self) -> GmailClient:
        if self._gmail is None:
            if self._secret is not None:
                self._gmail = GmailClient.from_secret(self._secret)
            elif self._use_env:
                self._gmail = GmailClient.from_env()
            else:
                assert self._credentials_path is not None and self._token_path is not None
                self._gmail = GmailClient.from_files(
                    self._credentials_path,
                    self._token_path,
                    allow_browser=self._allow_browser,
                )
        return self._gmail

    def _cal(self) -> CalendarClient:
        if self._calendar is None:
            if self._secret is not None:
                self._calendar = CalendarClient.from_secret(self._secret)
            elif self._use_env:
                self._calendar = CalendarClient.from_env()
            else:
                assert self._credentials_path is not None and self._token_path is not None
                self._calendar = CalendarClient.from_files(
                    self._credentials_path,
                    self._token_path,
                    allow_browser=self._allow_browser,
                )
        return self._calendar

    def read_emails(self, limit: int = 10) -> list[EmailItem]:
        messages = self._mail().list_messages("in:inbox", limit, include_body=False)
        return [
            EmailItem(
                provider=self.name,
                id=m.message_id,
                subject=m.subject,
                sender=m.sender,
                date=m.date,
            )
            for m in messages
        ]

    def list_calendars(self) -> list[CalendarRefItem]:
        return [
            CalendarRefItem(
                provider=self.name,
                id=cal.calendar_id,
                name=cal.summary,
                primary=cal.primary,
            )
            for cal in self._cal().list_calendars()
        ]

    def read_calendar(
        self,
        limit: int = 10,
        *,
        calendars: list[str] | None = None,
    ) -> list[CalendarItem]:
        calendar_ids = tuple(calendars) if calendars is not None else self._calendar_ids
        name_by_id = {ref.id: ref.name for ref in self.list_calendars()}
        per_calendar = max(limit, 1)
        items: list[CalendarItem] = []
        for calendar_id in calendar_ids:
            events = self._cal().list_events(calendar_id=calendar_id, max_events=per_calendar)
            label = name_by_id.get(calendar_id, calendar_id)
            for event in events:
                items.append(
                    CalendarItem(
                        provider=self.name,
                        id=event.event_id,
                        summary=event.summary,
                        start=event.start.display(),
                        end=event.end.display(),
                        calendar=label,
                    )
                )
        items.sort(key=lambda item: item.start)
        return items[:limit]

    # --- calendar sync (CalendarWriter) -------------------------------------------------------

    def _writer(self) -> CalendarClient:
        """Client with the event-write scope. File/env tokens use their own scopes (``auth.SCOPES``)."""
        if self._secret is None:
            return self._cal()
        if self._calendar_writer is None:
            self._calendar_writer = CalendarClient.from_secret(self._secret, write=True)
        return self._calendar_writer

    def list_events_between(
        self,
        start: datetime,
        end: datetime,
        *,
        calendars: list[str] | None = None,
    ) -> list[CalendarEventItem]:
        """Events overlapping [start, end) in the selected calendars, times in UTC, ordered by start."""
        calendar_ids = tuple(calendars) if calendars is not None else self._calendar_ids
        zones = self._calendar_zones()
        items: list[CalendarEventItem] = []
        for calendar_id in calendar_ids:
            zone = zones.get(calendar_id, "UTC")
            for event in self._cal().list_events_between(calendar_id, start, end):
                item = self._event_item(event, calendar_id, zone)
                if item is not None:
                    items.append(item)
        items.sort(key=lambda item: (item.start, item.calendar))
        return items

    def _calendar_zones(self) -> dict[str, str]:
        zones: dict[str, str] = {}
        for ref in self._cal().list_calendars():
            zone = ref.time_zone or "UTC"
            zones[ref.calendar_id] = zone
            if ref.primary:
                zones["primary"] = zone
        return zones

    def _event_item(self, event, calendar_id: str, zone: str) -> CalendarEventItem | None:
        event_start = event.start.as_utc(zone)
        event_end = event.end.as_utc(zone)
        if event_start is None or event_end is None:
            return None
        return CalendarEventItem(
            provider=self.name,
            id=event.event_id,
            calendar=calendar_id,
            summary=event.summary,
            start=event_start,
            end=event_end,
            all_day=event.start.all_day,
            location=event.location,
            busy=event.busy,
            external_key=event.external_key,
        )

    def free_busy(
        self,
        start: datetime,
        end: datetime,
        *,
        calendars: list[str] | None = None,
    ) -> FreeBusyResult:
        calendar_ids = list(calendars) if calendars is not None else list(self._calendar_ids)
        result = self._cal().free_busy(calendar_ids, start, end)
        return FreeBusyResult(
            items=[
                BusyItem(provider=self.name, calendar=b.calendar_id, start=b.start, end=b.end)
                for b in result.busy
            ],
            errors=dict(result.errors),
        )

    def upsert_event(self, calendar_id: str, event: EventWrite) -> WriteResult:
        written, created = self._writer().upsert_event(
            calendar_id,
            EventInput(
                summary=event.summary,
                start=event.start,
                end=event.end,
                external_key=event.external_key,
                description=event.description,
                location=event.location,
                time_zone=event.time_zone,
                busy=event.busy,
            ),
        )
        return WriteResult(provider=self.name, calendar=calendar_id, event_id=written.event_id, created=created)

    def delete_event(self, calendar_id: str, external_key: str) -> bool:
        return self._writer().delete_event(calendar_id, external_key)

    def _manager(self) -> CalendarClient:
        if self._secret is None:
            return self._cal()
        if self._calendar_manager is None:
            self._calendar_manager = CalendarClient.from_secret(self._secret, write=True, manage=True)
        return self._calendar_manager

    def sync_events(
        self,
        calendar_id: str,
        token: str | None = None,
        *,
        since: datetime | None = None,
    ) -> CalendarSyncResult:
        """Changes since ``token`` (see CalendarSyncResult). Events the app wrote itself carry ``external_key``,
        so the caller can tell its own bookings from events people made in the calendar."""
        step = self._cal().sync_events(calendar_id, token, since=since)
        zone = self._calendar_zones().get(calendar_id, "UTC")
        changed = [item for event in step.changed if (item := self._event_item(event, calendar_id, zone))]
        return CalendarSyncResult(
            provider=self.name,
            calendar=calendar_id,
            changed=changed,
            deleted_ids=list(step.deleted_ids),
            next_token=step.next_sync_token,
            full=step.full,
        )

    def create_calendar(self, name: str, *, time_zone: str = "UTC", description: str = "") -> CalendarRefItem:
        ref = self._manager().create_calendar(name, time_zone=time_zone, description=description)
        return CalendarRefItem(provider=self.name, id=ref.calendar_id, name=ref.summary, primary=False)

    def share_calendar(self, calendar_id: str, email: str, *, role: str = "reader") -> str:
        return self._manager().share_calendar(calendar_id, email, role=role)
