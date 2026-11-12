from datetime import UTC, datetime

import httplib2
import pytest
from fake_service import FakeCalendarService
from gcal_read.write import (
    CalendarApiError,
    create_calendar,
    share_calendar,
    sync_events,
)
from googleapiclient.errors import HttpError

SINCE = datetime(2026, 11, 1, tzinfo=UTC)


def _http_error(status: int) -> HttpError:
    return HttpError(httplib2.Response({"status": status}), b"{}")


def _item(event_id: str, status: str = "confirmed") -> dict:
    return {
        "id": event_id,
        "status": status,
        "summary": f"Meeting {event_id}",
        "start": {"dateTime": "2026-11-12T08:00:00Z"},
        "end": {"dateTime": "2026-11-12T09:00:00Z"},
    }


def test_full_sync_reads_all_pages_and_returns_token():
    service = FakeCalendarService()
    service.list_queue = [
        {"items": [_item("a")], "nextPageToken": "p2"},
        {"items": [_item("b")], "nextSyncToken": "tok-1"},
    ]

    result = sync_events(service, "room@group", since=SINCE)

    assert result.full is True
    assert [e.event_id for e in result.changed] == ["a", "b"]
    assert result.next_sync_token == "tok-1"
    first, second = service.calls[0][1], service.calls[1][1]
    assert first["timeMin"] == "2026-11-01T00:00:00Z"
    assert first["singleEvents"] is True
    assert "syncToken" not in first
    assert "showDeleted" not in first
    assert second["pageToken"] == "p2"


def test_incremental_sync_separates_cancelled_events():
    service = FakeCalendarService()
    service.list_queue = [
        {"items": [_item("a"), _item("b", "cancelled")], "nextSyncToken": "tok-2"}
    ]

    result = sync_events(service, "room@group", "tok-1")

    assert result.full is False
    assert [e.event_id for e in result.changed] == ["a"]
    assert result.deleted_ids == ["b"]
    assert result.next_sync_token == "tok-2"
    kwargs = service.calls[0][1]
    assert kwargs["syncToken"] == "tok-1"
    assert kwargs["showDeleted"] is True
    assert "timeMin" not in kwargs


def test_expired_token_falls_back_to_full_sync():
    service = FakeCalendarService()
    service.list_queue = [
        _http_error(410),
        {"items": [_item("a")], "nextSyncToken": "tok-new"},
    ]

    result = sync_events(service, "room@group", "old-token", since=SINCE)

    assert result.full is True
    assert result.next_sync_token == "tok-new"
    assert "syncToken" not in service.calls[1][1]
    assert service.calls[1][1]["timeMin"] == "2026-11-01T00:00:00Z"


def test_other_sync_errors_raise_with_status():
    service = FakeCalendarService()
    service.list_queue = [_http_error(404)]

    with pytest.raises(CalendarApiError) as err:
        sync_events(service, "gone@group", "tok")
    assert err.value.status == 404


def test_create_calendar():
    service = FakeCalendarService()

    ref = create_calendar(
        service, " Zasedačka 1 ", time_zone="Europe/Prague", description="Rezervace"
    )

    assert service.calls == [
        (
            "calendars.insert",
            {
                "summary": "Zasedačka 1",
                "timeZone": "Europe/Prague",
                "description": "Rezervace",
            },
        )
    ]
    assert ref.calendar_id == "new-cal@group.calendar.google.com"
    assert ref.summary == "Zasedačka 1"
    assert ref.access_role == "owner"
    assert ref.time_zone == "Europe/Prague"


def test_create_calendar_needs_a_name():
    with pytest.raises(ValueError, match="needs a name"):
        create_calendar(FakeCalendarService(), "  ")


def test_share_calendar():
    service = FakeCalendarService()

    rule = share_calendar(service, "new-cal@group", "recepce@firma.cz", role="writer")

    assert rule == "user:recepce@firma.cz"
    assert service.calls[0] == (
        "acl.insert",
        {
            "calendarId": "new-cal@group",
            "body": {
                "role": "writer",
                "scope": {"type": "user", "value": "recepce@firma.cz"},
            },
            "sendNotifications": False,
        },
    )


def test_share_calendar_rejects_unknown_role():
    with pytest.raises(ValueError, match="Unknown calendar role"):
        share_calendar(FakeCalendarService(), "c", "a@b.cz", role="admin")
