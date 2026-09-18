"""Local Calendar reader: authenticate once, then list calendars and events."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .auth import CalendarAuthError, CredentialsMissingError
from .client import CalendarClient
from .models import CalendarEvent, CalendarRef

DEFAULT_CALENDAR_ID = "primary"
DEFAULT_LIST_MAX = 20
DEFAULT_CREDENTIALS = "credentials/credentials.json"
DEFAULT_TOKEN = "token.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gcal-read",
        description="Read Google Calendar from a local client (desktop OAuth).",
    )
    parser.add_argument(
        "--credentials",
        default=DEFAULT_CREDENTIALS,
        help="Path to OAuth Desktop app credentials.json",
    )
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="Path to store/read the OAuth token")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="Sign in with Google in a browser and save token.json")

    sub.add_parser("calendars", help="List calendars available to the account")

    list_parser = sub.add_parser("list", help="List upcoming events")
    list_parser.add_argument(
        "--calendar",
        default=DEFAULT_CALENDAR_ID,
        dest="calendar_id",
        help=f"Calendar id (default: {DEFAULT_CALENDAR_ID!r})",
    )
    list_parser.add_argument("--from", dest="time_min", default=None, help="RFC3339 lower bound (default: now)")
    list_parser.add_argument("--to", dest="time_max", default=None, help="RFC3339 upper bound")
    list_parser.add_argument("--query", default=None, help="Free-text event search")
    list_parser.add_argument(
        "--max", type=int, default=DEFAULT_LIST_MAX, dest="max_events", help="Maximum events to list"
    )
    list_parser.add_argument("--json", action="store_true", dest="as_json", help="Print JSON instead of a table")

    get_parser = sub.add_parser("get", help="Read one event")
    get_parser.add_argument("event_id", help="Event id from `gcal-read list`")
    get_parser.add_argument(
        "--calendar",
        default=DEFAULT_CALENDAR_ID,
        dest="calendar_id",
        help=f"Calendar id (default: {DEFAULT_CALENDAR_ID!r})",
    )
    get_parser.add_argument("--json", action="store_true", dest="as_json", help="Print JSON")
    return parser


def _connect(args: argparse.Namespace, *, allow_browser: bool) -> CalendarClient:
    return CalendarClient.from_files(
        Path(args.credentials).resolve(),
        Path(args.token).resolve(),
        allow_browser=allow_browser,
    )


def _print_calendar_row(calendar: CalendarRef) -> None:
    marker = " *" if calendar.primary else ""
    print(f"{calendar.calendar_id}  {calendar.summary}{marker}")


def _print_event_row(event: CalendarEvent) -> None:
    summary = event.summary.replace("\n", " ")
    if len(summary) > 80:
        summary = summary[:77] + "..."
    print(f"{event.event_id}  {event.start.display()}  {summary}")


def _print_event(event: CalendarEvent) -> None:
    print(f"Id: {event.event_id}")
    print(f"Calendar: {event.calendar_id}")
    print(f"Summary: {event.summary}")
    print(f"Status: {event.status}")
    print(f"Start: {event.start.display()}")
    print(f"End: {event.end.display()}")
    if event.location:
        print(f"Location: {event.location}")
    if event.organizer:
        print(f"Organizer: {event.organizer}")
    if event.attendees:
        print(f"Attendees: {', '.join(event.attendees)}")
    if event.html_link:
        print(f"Link: {event.html_link}")
    if event.description:
        print()
        print(event.description)


def run(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(line_buffering=True)
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "auth":
            print("Authenticating with Google (Gmail + Calendar scopes)...")
            _connect(args, allow_browser=True)
            print(f"Signed in. Token saved to {Path(args.token).resolve()}")
            print("For Lambda, store this token.json as the GOOGLE_TOKEN_JSON secret.")
            return 0

        client = _connect(args, allow_browser=True)

        if args.command == "calendars":
            calendars = client.list_calendars()
            if getattr(args, "as_json", False):
                print(json.dumps([c.to_dict() for c in calendars], indent=2, ensure_ascii=False))
                return 0
            print(f"Calendars: {len(calendars)}")
            for calendar in calendars:
                _print_calendar_row(calendar)
            return 0

        if args.command == "list":
            events = client.list_events(
                calendar_id=args.calendar_id,
                time_min=args.time_min,
                time_max=args.time_max,
                query=args.query,
                max_events=args.max_events,
            )
            if args.as_json:
                print(json.dumps([e.to_dict() for e in events], indent=2, ensure_ascii=False))
                return 0
            print(f"Calendar: {args.calendar_id}")
            print(f"Matching events: {len(events)}")
            for event in events:
                _print_event_row(event)
            return 0

        if args.command == "get":
            event = client.get(args.event_id, calendar_id=args.calendar_id)
            if args.as_json:
                print(json.dumps(event.to_dict(), indent=2, ensure_ascii=False))
                return 0
            _print_event(event)
            return 0
    except (CredentialsMissingError, CalendarAuthError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"unknown command {args.command!r}")
    return 2


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
