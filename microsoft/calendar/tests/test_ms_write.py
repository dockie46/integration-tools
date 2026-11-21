from datetime import UTC, datetime, timedelta

import pytest
from fake_transport import FakeResponse, FakeTransport
from mscal_read.api import EXTERNAL_KEY_PROP
from mscal_read.graph import GraphApiError, GraphClient
from mscal_read.models import EventInput
from mscal_read.write import (
    decline_event,
    delete_event_by_key,
    event_body,
    free_busy,
    upsert_event,
)

START = datetime(2026, 11, 12, 8, tzinfo=UTC)
END = START + timedelta(hours=1)


def _client(*responses: FakeResponse) -> tuple[GraphClient, FakeTransport]:
    transport = FakeTransport(list(responses))
    return GraphClient(transport, base_url="https://graph.test/v1.0"), transport


def _input(key: str = "booking-1", *, busy: bool = True, tz: str = "Europe/Prague") -> EventInput:
    return EventInput("Porada", START, END, key, description="d", location="Praha 2", time_zone=tz, busy=busy)


def test_event_body_sends_local_wall_time_and_source_key():
    body = event_body(_input(busy=False))

    assert body["start"] == {"dateTime": "2026-11-12T09:00:00", "timeZone": "Europe/Prague"}
    assert body["showAs"] == "free"
    assert body["singleValueExtendedProperties"] == [{"id": EXTERNAL_KEY_PROP, "value": "booking-1"}]


def test_upsert_creates_when_no_match():
    graph, transport = _client(
        FakeResponse(body={"value": []}),
        FakeResponse(body={"id": "evt-new", "subject": "Porada", "start": {}, "end": {}, "showAs": "busy"}),
    )

    event, created = upsert_event(graph, "room@firma.cz", _input())

    assert created is True
    assert event.event_id == "evt-new"
    assert transport.calls[1]["method"] == "POST"
    assert transport.calls[1]["url"].endswith("/users/room@firma.cz/calendar/events")


def test_upsert_patches_when_key_matches():
    graph, transport = _client(
        FakeResponse(body={"value": [{"id": "evt-7"}]}),
        FakeResponse(body={"id": "evt-7", "subject": "Porada", "start": {}, "end": {}, "showAs": "busy"}),
    )

    event, created = upsert_event(graph, "room@firma.cz", _input())

    assert created is False
    assert event.event_id == "evt-7"
    assert transport.calls[1]["method"] == "PATCH"
    assert transport.calls[1]["url"].endswith("/users/room@firma.cz/events/evt-7")
    assert "booking-1" in transport.calls[0]["params"]["$filter"]


def test_delete_returns_false_when_nothing_to_delete():
    graph, _ = _client(FakeResponse(body={"value": []}))
    assert delete_event_by_key(graph, "room@firma.cz", "booking-x") is False


def test_delete_removes_matched_event():
    graph, transport = _client(
        FakeResponse(body={"value": [{"id": "evt-7"}]}),
        FakeResponse(status_code=204),
    )
    assert delete_event_by_key(graph, "room@firma.cz", "booking-1") is True
    assert transport.calls[1]["method"] == "DELETE"


def test_delete_treats_already_gone_as_false():
    graph, _ = _client(
        FakeResponse(body={"value": [{"id": "evt-7"}]}),
        FakeResponse(status_code=404, body={"error": {"code": "ErrorItemNotFound", "message": "gone"}}),
    )
    assert delete_event_by_key(graph, "room@firma.cz", "booking-1") is False


def test_free_busy_collects_busy_slots_and_errors():
    graph, transport = _client(
        FakeResponse(
            body={
                "value": [
                    {
                        "scheduleId": "room@firma.cz",
                        "scheduleItems": [
                            {"status": "busy", "start": {"dateTime": "2026-11-12T08:00:00.0000000", "timeZone": "UTC"},
                             "end": {"dateTime": "2026-11-12T09:00:00.0000000", "timeZone": "UTC"}},
                            {"status": "free", "start": {"dateTime": "2026-11-12T10:00:00.0000000", "timeZone": "UTC"},
                             "end": {"dateTime": "2026-11-12T11:00:00.0000000", "timeZone": "UTC"}},
                        ],
                    },
                    {"scheduleId": "bad@firma.cz", "error": {"message": "MailboxNotEnabledForRESTAPI"}},
                ]
            }
        )
    )

    result = free_busy(graph, ["room@firma.cz", "bad@firma.cz"], START, START + timedelta(hours=4))

    assert [(b.calendar_id, b.start.isoformat()) for b in result.busy] == [("room@firma.cz", "2026-11-12T08:00:00+00:00")]
    assert result.errors == {"bad@firma.cz": "MailboxNotEnabledForRESTAPI"}
    assert transport.calls[0]["json"]["schedules"] == ["room@firma.cz", "bad@firma.cz"]


def test_free_busy_without_calendars_is_empty():
    graph, transport = _client()
    result = free_busy(graph, [], START, END)
    assert result.busy == []
    assert result.errors == {}
    assert transport.calls == []


def test_api_error_carries_status():
    graph, _ = _client(FakeResponse(status_code=404, body={"error": {"code": "x", "message": "no room"}}))
    with pytest.raises(GraphApiError) as err:
        free_busy(graph, ["room@firma.cz"], START, END)
    assert err.value.status == 404


def test_decline_posts_to_the_room_and_sends_the_answer():
    graph, transport = _client(FakeResponse(status_code=202))

    assert decline_event(graph, "room@firma.cz", "evt-7", "Obsazeno") is True
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/users/room@firma.cz/events/evt-7/decline")
    assert call["json"] == {"comment": "Obsazeno", "sendResponse": True}


def test_decline_of_a_gone_event_is_false():
    graph, _ = _client(FakeResponse(status_code=404, body={"error": {"code": "ErrorItemNotFound", "message": "gone"}}))
    assert decline_event(graph, "room@firma.cz", "evt-7") is False
