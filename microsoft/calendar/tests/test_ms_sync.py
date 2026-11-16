from datetime import UTC, datetime

from fake_transport import FakeResponse, FakeTransport
from mscal_read.graph import GraphClient
from mscal_read.write import sync_events

SINCE = datetime(2026, 11, 1, tzinfo=UTC)
DELTA = "https://graph.test/v1.0/users/room@firma.cz/calendarView/delta?$deltatoken=abc"


def _client(*responses: FakeResponse) -> tuple[GraphClient, FakeTransport]:
    transport = FakeTransport(list(responses))
    return GraphClient(transport, base_url="https://graph.test/v1.0"), transport


def _event(event_id: str) -> dict:
    return {
        "id": event_id,
        "subject": f"Meeting {event_id}",
        "isAllDay": False,
        "isCancelled": False,
        "showAs": "busy",
        "start": {"dateTime": "2026-11-12T08:00:00.0000000", "timeZone": "UTC"},
        "end": {"dateTime": "2026-11-12T09:00:00.0000000", "timeZone": "UTC"},
    }


def test_full_sync_bounds_the_window_and_returns_delta_link():
    graph, transport = _client(
        FakeResponse(body={"value": [_event("a")], "@odata.nextLink": "https://graph.test/v1.0/delta?page=2"}),
        FakeResponse(body={"value": [_event("b")], "@odata.deltaLink": DELTA}),
    )

    result = sync_events(graph, "room@firma.cz", since=SINCE, horizon_days=30)

    assert result.full is True
    assert [e.event_id for e in result.changed] == ["a", "b"]
    assert result.next_token == DELTA
    first = transport.calls[0]
    assert first["url"].endswith("/users/room@firma.cz/calendarView/delta")
    assert first["params"]["startDateTime"] == "2026-11-01T00:00:00Z"
    assert first["params"]["endDateTime"] == "2026-12-01T00:00:00Z"
    assert transport.calls[1]["url"] == "https://graph.test/v1.0/delta?page=2"


def test_incremental_sync_follows_token_and_separates_removed():
    graph, transport = _client(
        FakeResponse(body={"value": [_event("a"), {"id": "b", "@removed": {"reason": "deleted"}}], "@odata.deltaLink": DELTA})
    )

    result = sync_events(graph, "room@firma.cz", DELTA)

    assert result.full is False
    assert [e.event_id for e in result.changed] == ["a"]
    assert result.deleted_ids == ["b"]
    assert result.next_token == DELTA
    assert transport.calls[0]["url"] == DELTA


def test_expired_token_falls_back_to_full_sync():
    graph, transport = _client(
        FakeResponse(status_code=410, body={"error": {"code": "syncStateNotFound", "message": "resync"}}),
        FakeResponse(body={"value": [_event("a")], "@odata.deltaLink": DELTA}),
    )

    result = sync_events(graph, "room@firma.cz", DELTA, since=SINCE)

    assert result.full is True
    assert result.next_token == DELTA
    assert transport.calls[0]["url"] == DELTA
    assert transport.calls[1]["url"].endswith("/users/room@firma.cz/calendarView/delta")
