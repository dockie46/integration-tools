"""AWS Lambda entry that reads Calendar with the same client as `gcal-read`.

Auth is headless: set GOOGLE_TOKEN_JSON (contents of token.json from local auth).
"""

from __future__ import annotations

import json
from typing import Any

from .auth import CalendarAuthError, CredentialsMissingError
from .client import CalendarClient
from .read_cli import DEFAULT_CALENDAR_ID, DEFAULT_LIST_MAX


def _payload(event: Any) -> dict:
    if not isinstance(event, dict):
        return {}
    if any(
        key in event
        for key in ("action", "calendar_id", "event_id", "max_events", "time_min", "time_max", "query")
    ):
        return event
    body = event.get("body")
    if isinstance(body, str) and body.strip():
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    if isinstance(body, dict):
        return body
    return {}


def _error(status_code: int, message: str) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"ok": False, "error": message}),
    }


def _ok(payload: dict) -> dict:
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"ok": True, **payload}, ensure_ascii=False),
    }


def lambda_handler(event: Any, context: Any) -> dict:
    payload = _payload(event)
    action = (payload.get("action") or "list").strip().lower()

    try:
        client = CalendarClient.from_env()
        if action == "calendars":
            calendars = client.list_calendars()
            return _ok({"action": "calendars", "calendars": [c.to_dict() for c in calendars]})
        if action == "list":
            calendar_id = payload.get("calendar_id") or DEFAULT_CALENDAR_ID
            max_events = int(payload.get("max_events") or DEFAULT_LIST_MAX)
            events = client.list_events(
                calendar_id=str(calendar_id),
                time_min=payload.get("time_min"),
                time_max=payload.get("time_max"),
                query=payload.get("query"),
                max_events=max_events,
            )
            return _ok(
                {
                    "action": "list",
                    "calendar_id": calendar_id,
                    "events": [e.to_dict() for e in events],
                }
            )
        if action == "get":
            event_id = payload.get("event_id")
            if not event_id:
                return _error(400, "event_id is required for action=get")
            calendar_id = payload.get("calendar_id") or DEFAULT_CALENDAR_ID
            calendar_event = client.get(str(event_id), calendar_id=str(calendar_id))
            return _ok({"action": "get", "event": calendar_event.to_dict()})
        return _error(400, f"Unknown action {action!r}. Use 'calendars', 'list', or 'get'.")
    except CredentialsMissingError as exc:
        return _error(401, str(exc))
    except CalendarAuthError as exc:
        return _error(401, str(exc))
    except Exception as exc:
        return _error(500, f"Calendar read failed: {exc}")
