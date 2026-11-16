"""Microsoft 365 provider adapter (Graph, app-only).

Unlike Google (per-user web OAuth), a Microsoft connection is a tenant-wide Entra ID app registration with admin
consent: the stored secret carries ``tenantId`` / ``clientId`` / ``clientSecret``. Calendars are room mailboxes
addressed by e-mail. Mail is not offered here.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from mscal_read.client import CalendarClient
from mscal_read.models import CalendarEvent, EventInput

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


def _secret_from_env() -> dict[str, Any] | None:
    raw = (os.environ.get("MICROSOFT_SECRET_JSON") or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _secret_calendar_ids(secret: Mapping[str, Any]) -> tuple[str, ...]:
    raw = next((v for k, v in secret.items() if str(k).lower() in ("rooms", "calendars")), None)
    if isinstance(raw, list | tuple):
        ids = tuple(str(item).strip() for item in raw if str(item).strip())
    elif raw:
        ids = tuple(part.strip() for part in str(raw).split(",") if part.strip())
    else:
        ids = ()
    return ids


class MicrosoftProvider:
    name = "microsoft"

    def __init__(
        self,
        *,
        secret: Mapping[str, Any],
        calendar_ids: tuple[str, ...] = (),
    ) -> None:
        self._secret = dict(secret)
        self._calendar_ids = calendar_ids
        self._calendar: CalendarClient | None = None

    @classmethod
    def available(cls, root: Path) -> bool:
        del root
        return _secret_from_env() is not None

    @classmethod
    def create(cls, root: Path, *, allow_browser: bool = True) -> MicrosoftProvider:
        del root, allow_browser
        secret = _secret_from_env()
        if secret is None:
            raise RuntimeError("Microsoft credentials not found in MICROSOFT_SECRET_JSON")
        return cls(secret=secret, calendar_ids=_secret_calendar_ids(secret))

    @classmethod
    def from_secret(
        cls,
        secret: Mapping[str, Any],
        *,
        calendar_ids: tuple[str, ...] | list[str] | None = None,
    ) -> MicrosoftProvider:
        """One tenant's Microsoft 365 account from its stored app-registration secret (no files, no browser)."""
        ids = tuple(calendar_ids) if calendar_ids else _secret_calendar_ids(secret)
        return cls(secret=secret, calendar_ids=ids)

    def _cal(self) -> CalendarClient:
        if self._calendar is None:
            self._calendar = CalendarClient.from_secret(self._secret)
        return self._calendar

    # --- Provider (mail + discovery) ----------------------------------------------------------

    def read_emails(self, limit: int = 10) -> list[EmailItem]:
        del limit
        return []

    def list_calendars(self) -> list[CalendarRefItem]:
        return [
            CalendarRefItem(provider=self.name, id=room.email, name=room.name, primary=False)
            for room in self._cal().list_rooms()
        ]

    def read_calendar(
        self,
        limit: int = 10,
        *,
        calendars: list[str] | None = None,
    ) -> list[CalendarItem]:
        from datetime import UTC, timedelta

        calendar_ids = tuple(calendars) if calendars is not None else self._calendar_ids
        start = datetime.now(UTC)
        end = start + timedelta(days=30)
        items: list[CalendarItem] = []
        for calendar_id in calendar_ids:
            items.extend(
                CalendarItem(
                    provider=self.name,
                    id=event.event_id,
                    summary=event.summary,
                    start=event.start.display(),
                    end=event.end.display(),
                    calendar=calendar_id,
                )
                for event in self._cal().list_events_between(calendar_id, start, end)
            )
        items.sort(key=lambda item: item.start)
        return items[:limit]

    # --- calendar sync (CalendarWriter) -------------------------------------------------------

    def _event_item(self, event: CalendarEvent, calendar_id: str) -> CalendarEventItem | None:
        start = event.start.as_utc()
        end = event.end.as_utc()
        if start is None or end is None:
            return None
        return CalendarEventItem(
            provider=self.name,
            id=event.event_id,
            calendar=calendar_id,
            summary=event.summary,
            start=start,
            end=end,
            all_day=event.is_all_day,
            location=event.location,
            busy=event.busy,
            external_key=event.external_key,
            organizer=event.organizer,
        )

    def list_events_between(
        self,
        start: datetime,
        end: datetime,
        *,
        calendars: list[str] | None = None,
    ) -> list[CalendarEventItem]:
        calendar_ids = tuple(calendars) if calendars is not None else self._calendar_ids
        items: list[CalendarEventItem] = []
        for calendar_id in calendar_ids:
            for event in self._cal().list_events_between(calendar_id, start, end):
                item = self._event_item(event, calendar_id)
                if item is not None:
                    items.append(item)
        items.sort(key=lambda item: (item.start, item.calendar))
        return items

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
        written, created = self._cal().upsert_event(
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
        return self._cal().delete_event(calendar_id, external_key)

    def sync_events(
        self,
        calendar_id: str,
        token: str | None = None,
        *,
        since: datetime | None = None,
    ) -> CalendarSyncResult:
        step = self._cal().sync_events(calendar_id, token, since=since)
        changed = [item for event in step.changed if (item := self._event_item(event, calendar_id))]
        return CalendarSyncResult(
            provider=self.name,
            calendar=calendar_id,
            changed=changed,
            deleted_ids=list(step.deleted_ids),
            next_token=step.next_token,
            full=step.full,
        )

    def create_calendar(self, name: str, *, time_zone: str = "UTC", description: str = "") -> CalendarRefItem:
        del name, time_zone, description
        raise NotImplementedError(
            "Microsoft 365 rooms are provisioned as room mailboxes in Exchange; the platform does not create them."
        )

    def share_calendar(self, calendar_id: str, email: str, *, role: str = "reader") -> str:
        del calendar_id, email, role
        raise NotImplementedError("Sharing is managed in Exchange for Microsoft 365 room mailboxes.")
