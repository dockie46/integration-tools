from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httplib2
import pytest
from fake_service import FakeCalendarService
from gcal_read.api import EXTERNAL_KEY_PROPERTY, parse_event
from gcal_read.models import EventInput, EventTime
from gcal_read.write import (
    CalendarApiError,
    delete_event_by_key,
    event_body,
    free_busy,
    list_events_between,
    to_rfc3339,
    upsert_event,
)
from googleapiclient.errors import HttpError

PRAGUE = ZoneInfo("Europe/Prague")
START = datetime(2026, 11, 12, 9, 0, tzinfo=PRAGUE)
END = START + timedelta(hours=1)
KEY_FILTER = f"{EXTERNAL_KEY_PROPERTY}=booking-42"


def _event(**overrides) -> EventInput:
    data = {
        "summary": "Rental: Box 1",
        "start": START,
        "end": END,
        "external_key": "booking-42",
        "time_zone": "Europe/Prague",
    }
    data.update(overrides)
    return EventInput(**data)


def _http_error(status: int) -> HttpError:
    return HttpError(httplib2.Response({"status": status}), b"{}")


def test_to_rfc3339_is_utc_z():
    assert to_rfc3339(START) == "2026-11-12T08:00:00Z"


def test_to_rfc3339_rejects_naive():
    with pytest.raises(ValueError, match="timezone-aware"):
        to_rfc3339(datetime(2026, 11, 12, 9, 0))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"start": datetime(2026, 11, 12, 9, 0)}, "timezone-aware"),
        ({"end": START}, "end after it starts"),
        ({"external_key": " "}, "external_key"),
    ],
)
def test_event_input_validation(overrides, message):
    with pytest.raises(ValueError, match=message):
        _event(**overrides)


def test_event_body_carries_key_and_busy_state():
    body = event_body(_event(busy=False, description="Jan Novák", location="Sklad A"))

    assert body["start"] == {
        "dateTime": "2026-11-12T08:00:00Z",
        "timeZone": "Europe/Prague",
    }
    assert body["end"] == {
        "dateTime": "2026-11-12T09:00:00Z",
        "timeZone": "Europe/Prague",
    }
    assert body["transparency"] == "transparent"
    assert body["extendedProperties"] == {
        "private": {EXTERNAL_KEY_PROPERTY: "booking-42"}
    }
    assert body["description"] == "Jan Novák"
    assert body["location"] == "Sklad A"


def test_upsert_creates_when_key_unknown():
    service = FakeCalendarService()

    event, created = upsert_event(service, "team@group", _event())

    assert created is True
    assert event.event_id == "new-1"
    assert event.external_key == "booking-42"
    assert [c[0] for c in service.calls] == ["list", "insert"]
    assert service.calls[0][1]["privateExtendedProperty"] == KEY_FILTER
    assert service.calls[1][1]["calendarId"] == "team@group"


def test_upsert_updates_event_with_same_key():
    service = FakeCalendarService()
    service.by_key[KEY_FILTER] = [{"id": "evt-7"}]

    event, created = upsert_event(service, "primary", _event(summary="Rental: Box 2"))

    assert created is False
    assert event.event_id == "evt-7"
    assert event.summary == "Rental: Box 2"
    assert [c[0] for c in service.calls] == ["list", "patch"]


def test_delete_by_key():
    service = FakeCalendarService()
    service.by_key[KEY_FILTER] = [{"id": "evt-7"}]

    assert delete_event_by_key(service, "primary", "booking-42") is True
    assert service.calls[-1] == (
        "delete",
        {"calendarId": "primary", "eventId": "evt-7"},
    )


def test_delete_missing_key_is_false():
    service = FakeCalendarService()

    assert delete_event_by_key(service, "primary", "booking-42") is False
    assert [c[0] for c in service.calls] == ["list"]


def test_delete_already_gone_is_false():
    service = FakeCalendarService()
    service.by_key[KEY_FILTER] = [{"id": "evt-7"}]
    service.delete_error = _http_error(410)

    assert delete_event_by_key(service, "primary", "booking-42") is False


def test_delete_forbidden_raises_with_status():
    service = FakeCalendarService()
    service.by_key[KEY_FILTER] = [{"id": "evt-7"}]
    service.delete_error = _http_error(403)

    with pytest.raises(CalendarApiError, match="no permission") as err:
        delete_event_by_key(service, "primary", "booking-42")
    assert err.value.status == 403


def test_list_events_between_sends_window():
    service = FakeCalendarService()
    service.window_items = [
        {
            "id": "a",
            "summary": "Porada",
            "start": {"dateTime": "2026-11-12T08:00:00Z"},
            "end": {"dateTime": "2026-11-12T09:00:00Z"},
        }
    ]

    events = list_events_between(service, "room@group", START, END)

    kwargs = service.calls[0][1]
    assert kwargs["timeMin"] == "2026-11-12T08:00:00Z"
    assert kwargs["timeMax"] == "2026-11-12T09:00:00Z"
    assert kwargs["singleEvents"] is True
    assert [e.event_id for e in events] == ["a"]


def test_list_events_between_rejects_empty_window():
    with pytest.raises(ValueError, match="end must be after start"):
        list_events_between(FakeCalendarService(), "primary", END, START)


def test_free_busy_parses_busy_and_errors():
    service = FakeCalendarService()
    service.freebusy_data = {
        "room@group": {
            "busy": [{"start": "2026-11-12T08:30:00Z", "end": "2026-11-12T09:00:00Z"}]
        },
        "secret@group": {"errors": [{"reason": "notFound"}]},
    }

    result = free_busy(
        service, ["room@group", "secret@group", "room@group"], START, END
    )

    body = service.calls[0][1]
    assert body["items"] == [{"id": "room@group"}, {"id": "secret@group"}]
    assert [(b.calendar_id, b.start.hour, b.end.hour) for b in result.busy] == [
        ("room@group", 8, 9)
    ]
    assert result.busy[0].start.tzinfo == UTC
    assert result.errors == {"secret@group": "notFound"}
    assert result.for_calendar("room@group") == result.busy


def test_free_busy_chunks_by_fifty():
    service = FakeCalendarService()

    free_busy(service, [f"c{i}" for i in range(120)], START, END)

    assert [len(c[1]["items"]) for c in service.calls] == [50, 50, 20]


def test_parse_event_reads_key_and_transparency():
    event = parse_event(
        {
            "id": "x",
            "status": "confirmed",
            "transparency": "transparent",
            "start": {"date": "2026-11-12"},
            "end": {"date": "2026-11-13"},
            "extendedProperties": {"private": {EXTERNAL_KEY_PROPERTY: "booking-1"}},
        },
        calendar_id="primary",
    )

    assert event.external_key == "booking-1"
    assert event.busy is False
    assert event.start.all_day is True


def test_event_time_as_utc():
    assert EventTime(date_time="2026-11-12T09:00:00+01:00").as_utc() == datetime(
        2026, 11, 12, 8, 0, tzinfo=UTC
    )
    assert EventTime(date="2026-11-12").as_utc("Europe/Prague") == datetime(
        2026, 11, 11, 23, 0, tzinfo=UTC
    )
    assert EventTime(
        date_time="2026-11-12T09:00:00", time_zone="Europe/Prague"
    ).as_utc() == datetime(2026, 11, 12, 8, 0, tzinfo=UTC)
    assert EventTime().as_utc() is None
