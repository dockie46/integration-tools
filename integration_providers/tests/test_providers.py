"""Unit tests for Providers factory (no network)."""

from __future__ import annotations

from integration_providers.models import CalendarItem, CalendarRefItem, EmailItem
from integration_providers.registry import Providers


class _FakeProvider:
    def __init__(self, name: str, *, calendar: str = "Main") -> None:
        self.name = name
        self._calendar = calendar

    def read_emails(self, limit: int = 10) -> list[EmailItem]:
        return [
            EmailItem(
                provider=self.name,
                id=f"{self.name}-1",
                subject="Hello",
                sender="a@example.com",
                date="2026-09-18T10:00:00+00:00",
            )
        ][:limit]

    def list_calendars(self) -> list[CalendarRefItem]:
        return [
            CalendarRefItem(
                provider=self.name,
                id=f"{self.name}-cal",
                name=self._calendar,
                primary=True,
            )
        ]

    def read_calendar(
        self,
        limit: int = 10,
        *,
        calendars: list[str] | None = None,
    ) -> list[CalendarItem]:
        label = (calendars[0] if calendars else self._calendar)
        return [
            CalendarItem(
                provider=self.name,
                id=f"{self.name}-e1",
                summary="Standup",
                start="2026-09-18T11:00:00+00:00",
                end="2026-09-18T11:30:00+00:00",
                calendar=label,
            )
        ][:limit]


def test_read_emails_selected_providers() -> None:
    p = Providers({"google": _FakeProvider("google"), "icloud": _FakeProvider("icloud")})
    items = p.read_emails("google", "icloud", limit=1)
    assert [i.provider for i in items] == ["google", "icloud"]


def test_read_calendar_merges_and_limits() -> None:
    p = Providers({"google": _FakeProvider("google"), "icloud": _FakeProvider("icloud")})
    items = p.read_calendar(limit=1)
    assert len(items) == 1


def test_list_calendars() -> None:
    p = Providers({"google": _FakeProvider("google")})
    refs = p.list_calendars("google")
    assert refs[0].name == "Main"


def test_read_calendar_calendars_override() -> None:
    p = Providers({"google": _FakeProvider("google")})
    items = p.read_calendar("google", calendars=["Work"])
    assert items[0].calendar == "Work"


def test_discover_uses_catalog_not_hardcoded_ifs(tmp_path) -> None:
    (tmp_path / "credentials").mkdir()
    (tmp_path / "credentials" / "icloud.json").write_text(
        '{"email": "a@icloud.com", "password": "xxxx-xxxx-xxxx-xxxx"}'
    )
    p = Providers.discover(root=tmp_path, allow_browser=False)
    assert p.names == ["icloud"]
