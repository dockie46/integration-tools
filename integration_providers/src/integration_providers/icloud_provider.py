"""iCloud provider adapter."""

from __future__ import annotations

import json
import os
from pathlib import Path

from icloud_read.auth import ICloudCredentials, load_credentials
from icloud_read.calendar_client import ICloudCalendarClient
from icloud_read.mail_client import ICloudMailClient

from .models import CalendarItem, CalendarRefItem, EmailItem


def _credentials_from_env() -> ICloudCredentials | None:
    raw = (os.environ.get("ICLOUD_JSON") or "").strip()
    if raw:
        data = json.loads(raw)
        email = (data.get("email") or "").strip()
        password = (data.get("password") or "").strip()
        calendars_raw = data.get("calendars")
        calendars = None
        if isinstance(calendars_raw, list):
            parsed = tuple(str(x).strip() for x in calendars_raw if str(x).strip())
            calendars = parsed or None
        if email and password:
            return ICloudCredentials(email=email, password=password, calendars=calendars)

    email = (os.environ.get("ICLOUD_EMAIL") or "").strip()
    password = (os.environ.get("ICLOUD_PASSWORD") or "").strip()
    if not email or not password:
        return None
    cal_env = (os.environ.get("ICLOUD_CALENDARS") or "").strip()
    calendars = tuple(p.strip() for p in cal_env.split(",") if p.strip()) or None
    return ICloudCredentials(email=email, password=password, calendars=calendars)


class ICloudProvider:
    name = "icloud"

    def __init__(
        self,
        credentials: ICloudCredentials,
        *,
        calendar_names: tuple[str, ...] | None = None,
    ) -> None:
        self._credentials = credentials
        self._calendar_names = (
            calendar_names if calendar_names is not None else credentials.calendars
        )
        self._mail: ICloudMailClient | None = None
        self._calendar: ICloudCalendarClient | None = None

    @classmethod
    def available(cls, root: Path) -> bool:
        if (root / "credentials" / "icloud.json").exists():
            return True
        try:
            return _credentials_from_env() is not None
        except json.JSONDecodeError:
            return False

    @classmethod
    def create(cls, root: Path, *, allow_browser: bool = True) -> ICloudProvider:
        del allow_browser
        path = root / "credentials" / "icloud.json"
        if path.exists():
            creds = load_credentials(path)
            return cls(creds, calendar_names=creds.calendars)
        creds = _credentials_from_env()
        if creds is None:
            raise RuntimeError("iCloud credentials not found in file or environment")
        return cls(creds, calendar_names=creds.calendars)

    def _mail_client(self) -> ICloudMailClient:
        if self._mail is None:
            self._mail = ICloudMailClient(self._credentials)
        return self._mail

    def _cal_client(self) -> ICloudCalendarClient:
        if self._calendar is None:
            self._calendar = ICloudCalendarClient(self._credentials)
        return self._calendar

    def read_emails(self, limit: int = 10) -> list[EmailItem]:
        messages = self._mail_client().list_messages(limit)
        return [
            EmailItem(
                provider=self.name,
                id=m.uid,
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
            )
            for cal in self._cal_client().list_calendars()
        ]

    def read_calendar(
        self,
        limit: int = 10,
        *,
        calendars: list[str] | None = None,
    ) -> list[CalendarItem]:
        names = tuple(calendars) if calendars is not None else self._calendar_names
        events = self._cal_client().list_events(limit, calendar_names=names)
        return [
            CalendarItem(
                provider=self.name,
                id=e.uid,
                summary=e.summary,
                start=e.start,
                end=e.end,
                calendar=e.calendar,
            )
            for e in events
        ]
