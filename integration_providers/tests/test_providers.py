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


def test_google_provider_from_secret_uses_secret_clients(monkeypatch):
    from integration_providers.google_provider import GoogleProvider

    seen = []

    class _Cal:
        def list_calendars(self):
            return []

        def list_events(self, **kwargs):
            seen.append(kwargs["calendar_id"])
            return []

    monkeypatch.setattr(
        "integration_providers.google_provider.CalendarClient.from_secret",
        classmethod(lambda _cls, _secret: _Cal()),
    )

    provider = GoogleProvider.from_secret({"refreshToken": "rt", "calendars": "primary, team@group"})

    assert provider.read_calendar(limit=5) == []
    assert seen == ["primary", "team@group"]


def _secret_provider(monkeypatch, *, reader, writer=None):
    from integration_providers.google_provider import GoogleProvider

    def from_secret(cls, secret, *, write=False):
        return writer if write else reader

    monkeypatch.setattr(
        "integration_providers.google_provider.CalendarClient.from_secret", classmethod(from_secret)
    )
    return GoogleProvider.from_secret({"refreshToken": "rt"}, calendar_ids=["primary", "room@group"])


def test_google_provider_events_between_in_utc(monkeypatch):
    from datetime import UTC, datetime

    from gcal_read.models import CalendarEvent, CalendarRef, EventTime

    class _Reader:
        def list_calendars(self):
            return [CalendarRef("me@firma.cz", "Me", primary=True, time_zone="Europe/Prague")]

        def list_events_between(self, calendar_id, start, end):
            if calendar_id == "primary":
                return [
                    CalendarEvent(
                        "e1", calendar_id, "Dovolená", "confirmed",
                        EventTime(date="2026-11-12"), EventTime(date="2026-11-13"),
                    )
                ]
            return [
                CalendarEvent(
                    "e2", calendar_id, "Porada", "confirmed",
                    EventTime(date_time="2026-11-12T08:00:00Z"), EventTime(date_time="2026-11-12T09:00:00Z"),
                    transparency="transparent", external_key="booking-1",
                )
            ]

    provider = _secret_provider(monkeypatch, reader=_Reader())
    start = datetime(2026, 11, 12, tzinfo=UTC)

    items = provider.list_events_between(start, start.replace(day=13))

    assert [(i.id, i.calendar, i.start.isoformat(), i.all_day, i.busy) for i in items] == [
        ("e1", "primary", "2026-11-11T23:00:00+00:00", True, True),
        ("e2", "room@group", "2026-11-12T08:00:00+00:00", False, False),
    ]
    assert items[1].external_key == "booking-1"


def test_google_provider_free_busy_and_writes(monkeypatch):
    from datetime import UTC, datetime, timedelta

    from gcal_read.models import BusyInterval, CalendarEvent, EventTime, FreeBusy

    from integration_providers.models import EventWrite

    start = datetime(2026, 11, 12, 8, tzinfo=UTC)
    end = start + timedelta(hours=1)

    class _Reader:
        def free_busy(self, calendar_ids, s, e):
            assert calendar_ids == ["primary", "room@group"]
            return FreeBusy(busy=[BusyInterval("room@group", s, e)], errors={"primary": "notFound"})

    class _Writer:
        def __init__(self):
            self.written = []

        def upsert_event(self, calendar_id, event):
            self.written.append((calendar_id, event))
            return CalendarEvent("evt-9", calendar_id, event.summary, "confirmed", EventTime(), EventTime()), True

        def delete_event(self, calendar_id, key):
            return key == "booking-1"

    writer = _Writer()
    provider = _secret_provider(monkeypatch, reader=_Reader(), writer=writer)

    busy = provider.free_busy(start, end)
    assert [(b.calendar, b.start, b.end) for b in busy.items] == [("room@group", start, end)]
    assert busy.errors == {"primary": "notFound"}

    result = provider.upsert_event(
        "room@group", EventWrite("Rental", start, end, "booking-1", time_zone="Europe/Prague", busy=False)
    )
    assert result.to_dict() == {"provider": "google", "calendar": "room@group", "event_id": "evt-9", "created": True}
    written = writer.written[0][1]
    assert (written.external_key, written.time_zone, written.busy) == ("booking-1", "Europe/Prague", False)

    assert provider.delete_event("room@group", "booking-1") is True
    assert provider.delete_event("room@group", "booking-2") is False


def test_google_provider_sync_and_create_calendar(monkeypatch):
    from gcal_read.models import CalendarEvent, CalendarRef, EventSync, EventTime

    from integration_providers.google_provider import GoogleProvider

    clients = {}

    class _Client:
        def list_calendars(self):
            return [CalendarRef("room@group", "Zasedačka", time_zone="Europe/Prague")]

        def sync_events(self, calendar_id, token, *, since=None):
            assert (calendar_id, token) == ("room@group", "tok-1")
            event = CalendarEvent(
                "e1", calendar_id, "Porada", "confirmed",
                EventTime(date="2026-11-12"), EventTime(date="2026-11-13"),
            )
            return EventSync(changed=[event], deleted_ids=["old"], next_sync_token="tok-2", full=False)

        def create_calendar(self, name, *, time_zone="UTC", description=""):
            return CalendarRef("new@group", name, time_zone=time_zone)

        def share_calendar(self, calendar_id, email, *, role="reader"):
            return f"{calendar_id}:{email}:{role}"

    def from_secret(cls, secret, *, write=False, manage=False):
        clients.setdefault((write, manage), _Client())
        return clients[(write, manage)]

    monkeypatch.setattr(
        "integration_providers.google_provider.CalendarClient.from_secret", classmethod(from_secret)
    )
    provider = GoogleProvider.from_secret({"refreshToken": "rt"})

    result = provider.sync_events("room@group", "tok-1")
    assert result.next_token == "tok-2"
    assert result.deleted_ids == ["old"]
    assert result.changed[0].start.isoformat() == "2026-11-11T23:00:00+00:00"
    assert result.to_dict()["changed"][0]["id"] == "e1"

    created = provider.create_calendar("Zasedačka 2", time_zone="Europe/Prague")
    assert (created.id, created.name) == ("new@group", "Zasedačka 2")
    assert provider.share_calendar("new@group", "a@firma.cz", role="writer") == "new@group:a@firma.cz:writer"
    assert (True, True) in clients
