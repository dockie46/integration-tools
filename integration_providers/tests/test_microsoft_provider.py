"""Unit tests for the Microsoft 365 provider adapter (no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mscal_read.models import (
    BusyInterval,
    CalendarEvent,
    EventSync,
    EventTime,
    FreeBusy,
    RoomRef,
)

from integration_providers.microsoft_provider import MicrosoftProvider
from integration_providers.models import EventWrite

START = datetime(2026, 11, 12, 8, tzinfo=UTC)
END = START + timedelta(hours=1)


def _event(event_id: str, *, key: str = "", show_as: str = "busy") -> CalendarEvent:
    return CalendarEvent(
        event_id=event_id,
        calendar_id="room@firma.cz",
        subject="Porada",
        start=EventTime(date_time="2026-11-12T08:00:00", time_zone="UTC"),
        end=EventTime(date_time="2026-11-12T09:00:00", time_zone="UTC"),
        show_as=show_as,
        organizer="jana@firma.cz",
        external_key=key,
    )


def _provider(monkeypatch, client) -> MicrosoftProvider:
    monkeypatch.setattr(
        "integration_providers.microsoft_provider.CalendarClient.from_secret",
        classmethod(lambda _cls, _secret: client),
    )
    return MicrosoftProvider.from_secret(
        {"tenantId": "t", "clientId": "c", "clientSecret": "s"}, calendar_ids=["room@firma.cz"]
    )


def test_list_calendars_maps_rooms(monkeypatch):
    class _Client:
        def list_rooms(self):
            return [RoomRef(email="room@firma.cz", name="Praha 2")]

    refs = _provider(monkeypatch, _Client()).list_calendars()
    assert [(r.id, r.name, r.provider) for r in refs] == [("room@firma.cz", "Praha 2", "microsoft")]


def test_events_between_in_utc_with_external_key(monkeypatch):
    class _Client:
        def list_events_between(self, calendar_id, start, end):
            return [_event("e1", key="booking-1", show_as="free"), _event("e2")]

    items = _provider(monkeypatch, _Client()).list_events_between(START, END)
    assert [(i.id, i.start.isoformat(), i.busy, i.external_key) for i in items] == [
        ("e1", "2026-11-12T08:00:00+00:00", False, "booking-1"),
        ("e2", "2026-11-12T08:00:00+00:00", True, ""),
    ]
    assert all(i.provider == "microsoft" for i in items)
    assert items[0].organizer == "jana@firma.cz"


def test_free_busy_maps_items_and_errors(monkeypatch):
    class _Client:
        def free_busy(self, calendar_ids, start, end):
            assert calendar_ids == ["room@firma.cz"]
            return FreeBusy(busy=[BusyInterval("room@firma.cz", START, END)], errors={"bad@firma.cz": "notFound"})

    busy = _provider(monkeypatch, _Client()).free_busy(START, END)
    assert [(b.calendar, b.start) for b in busy.items] == [("room@firma.cz", START)]
    assert busy.errors == {"bad@firma.cz": "notFound"}


def test_upsert_and_delete(monkeypatch):
    class _Client:
        def __init__(self):
            self.written = []

        def upsert_event(self, calendar_id, event):
            self.written.append((calendar_id, event))
            return _event("evt-9"), True

        def delete_event(self, calendar_id, key):
            return key == "booking-1"

    client = _Client()
    provider = _provider(monkeypatch, client)

    result = provider.upsert_event(
        "room@firma.cz", EventWrite("Porada", START, END, "booking-1", time_zone="Europe/Prague", busy=False)
    )
    assert result.to_dict() == {"provider": "microsoft", "calendar": "room@firma.cz", "event_id": "evt-9", "created": True}
    assert client.written[0][1].external_key == "booking-1"
    assert provider.delete_event("room@firma.cz", "booking-1") is True
    assert provider.delete_event("room@firma.cz", "booking-2") is False


def test_sync_maps_changes(monkeypatch):
    class _Client:
        def sync_events(self, calendar_id, token, *, since=None):
            assert (calendar_id, token) == ("room@firma.cz", "delta-1")
            return EventSync(changed=[_event("e1", key="booking-1")], deleted_ids=["old"], next_token="delta-2", full=False)

    result = _provider(monkeypatch, _Client()).sync_events("room@firma.cz", "delta-1")
    assert result.next_token == "delta-2"
    assert result.deleted_ids == ["old"]
    assert result.changed[0].external_key == "booking-1"
    assert result.to_dict()["changed"][0]["id"] == "e1"
