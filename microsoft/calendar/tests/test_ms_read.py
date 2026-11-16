from datetime import UTC, datetime

import pytest
from fake_transport import FakeResponse, FakeTransport
from mscal_read.api import EXTERNAL_KEY_PROP, calendar_view, list_rooms
from mscal_read.graph import GraphClient


def _client(*responses: FakeResponse) -> tuple[GraphClient, FakeTransport]:
    transport = FakeTransport(list(responses))
    return GraphClient(transport, base_url="https://graph.test/v1.0"), transport


def _event(event_id: str, *, show_as: str = "busy", key: str = "", all_day: bool = False) -> dict:
    item = {
        "id": event_id,
        "subject": f"Meeting {event_id}",
        "isAllDay": all_day,
        "isCancelled": False,
        "showAs": show_as,
        "start": {"dateTime": "2026-11-12T08:00:00.0000000", "timeZone": "UTC"},
        "end": {"dateTime": "2026-11-12T09:00:00.0000000", "timeZone": "UTC"},
        "organizer": {"emailAddress": {"name": "Jana", "address": "jana@firma.cz"}},
        "location": {"displayName": "Praha 2"},
    }
    if key:
        item["singleValueExtendedProperties"] = [{"id": EXTERNAL_KEY_PROP, "value": key}]
    return item


def test_calendar_view_parses_times_in_utc_and_external_key():
    graph, transport = _client(FakeResponse(body={"value": [_event("a", key="booking-1")]}))

    events = calendar_view(graph, "room@firma.cz", datetime(2026, 11, 12, tzinfo=UTC), datetime(2026, 11, 13, tzinfo=UTC))

    assert [e.event_id for e in events] == ["a"]
    assert events[0].start.as_utc().isoformat() == "2026-11-12T08:00:00+00:00"
    assert events[0].busy is True
    assert events[0].organizer == "jana@firma.cz"
    assert events[0].external_key == "booking-1"
    call = transport.calls[0]
    assert call["url"].endswith("/users/room@firma.cz/calendarView")
    assert call["params"]["startDateTime"] == "2026-11-12T00:00:00Z"
    assert call["headers"]["Prefer"] == 'outlook.timezone="UTC"'


def test_calendar_view_follows_next_link():
    graph, transport = _client(
        FakeResponse(body={"value": [_event("a")], "@odata.nextLink": "https://graph.test/v1.0/next?page=2"}),
        FakeResponse(body={"value": [_event("b")]}),
    )

    events = calendar_view(graph, "room@firma.cz", datetime(2026, 11, 12, tzinfo=UTC), datetime(2026, 11, 13, tzinfo=UTC))

    assert [e.event_id for e in events] == ["a", "b"]
    assert transport.calls[1]["url"] == "https://graph.test/v1.0/next?page=2"


def test_free_event_does_not_block_time():
    graph, _ = _client(FakeResponse(body={"value": [_event("a", show_as="free")]}))

    events = calendar_view(graph, "room@firma.cz", datetime(2026, 11, 12, tzinfo=UTC), datetime(2026, 11, 13, tzinfo=UTC))

    assert events[0].busy is False


def test_all_day_event_starts_at_local_midnight():
    item = _event("a", all_day=True)
    item["start"] = {"dateTime": "2026-11-12T00:00:00.0000000", "timeZone": "Europe/Prague"}
    item["end"] = {"dateTime": "2026-11-13T00:00:00.0000000", "timeZone": "Europe/Prague"}
    graph, _ = _client(FakeResponse(body={"value": [item]}))

    events = calendar_view(graph, "room@firma.cz", datetime(2026, 11, 12, tzinfo=UTC), datetime(2026, 11, 14, tzinfo=UTC))

    assert events[0].is_all_day is True
    assert events[0].start.as_utc().isoformat() == "2026-11-11T23:00:00+00:00"


def test_calendar_view_rejects_empty_window():
    graph, _ = _client()
    moment = datetime(2026, 11, 12, tzinfo=UTC)
    with pytest.raises(ValueError, match="end must be after start"):
        calendar_view(graph, "room@firma.cz", moment, moment)


def test_list_rooms_skips_rooms_without_email_and_pages():
    graph, _ = _client(
        FakeResponse(
            body={
                "value": [{"displayName": "Praha 2", "emailAddress": "praha2@firma.cz"}],
                "@odata.nextLink": "https://graph.test/v1.0/places?page=2",
            }
        ),
        FakeResponse(body={"value": [{"displayName": "No mailbox", "emailAddress": ""}]}),
    )

    rooms = list_rooms(graph)

    assert [(r.email, r.name) for r in rooms] == [("praha2@firma.cz", "Praha 2")]
