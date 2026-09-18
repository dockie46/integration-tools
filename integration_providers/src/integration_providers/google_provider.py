"""Google provider adapter."""

from __future__ import annotations

import json
import os
from pathlib import Path

from gcal_read.client import CalendarClient
from gmail_read.client import GmailClient

from .models import CalendarItem, CalendarRefItem, EmailItem


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
    ) -> None:
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._allow_browser = allow_browser
        self._use_env = use_env
        self._calendar_ids = calendar_ids
        self._gmail: GmailClient | None = None
        self._calendar: CalendarClient | None = None

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

    def _mail(self) -> GmailClient:
        if self._gmail is None:
            if self._use_env:
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
            if self._use_env:
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
