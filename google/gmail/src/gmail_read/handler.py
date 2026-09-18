"""AWS Lambda entry that reads Gmail with the same client as `gmail-read`.

Auth is headless: set GMAIL_TOKEN_JSON (contents of token.json from `gmail-read auth`).
No browser flow runs here.

Event examples:
  {"action": "list", "query": "in:inbox", "max_messages": 10}
  {"action": "get", "message_id": "18c2a1b3f"}
"""

from __future__ import annotations

import json
from typing import Any

from .auth import CredentialsMissingError, GmailAuthError
from .client import GmailClient
from .read_cli import DEFAULT_LIST_MAX, DEFAULT_LIST_QUERY


def _payload(event: Any) -> dict:
    if not isinstance(event, dict):
        return {}
    if any(key in event for key in ("action", "query", "message_id", "max_messages")):
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
    """Lambda handler. Direct invoke or API Gateway proxy events both work."""
    payload = _payload(event)
    action = (payload.get("action") or "list").strip().lower()

    try:
        client = GmailClient.from_env()
        if action == "list":
            query = payload.get("query") or DEFAULT_LIST_QUERY
            max_messages = int(payload.get("max_messages") or DEFAULT_LIST_MAX)
            include_body = bool(payload.get("include_body", False))
            messages = client.list_messages(query, max_messages, include_body=include_body)
            return _ok(
                {
                    "action": "list",
                    "query": query,
                    "messages": [message.to_dict() for message in messages],
                }
            )
        if action == "get":
            message_id = payload.get("message_id")
            if not message_id:
                return _error(400, "message_id is required for action=get")
            message = client.get(str(message_id), include_body=True)
            return _ok({"action": "get", "message": message.to_dict()})
        return _error(400, f"Unknown action {action!r}. Use 'list' or 'get'.")
    except CredentialsMissingError as exc:
        return _error(401, str(exc))
    except GmailAuthError as exc:
        return _error(401, str(exc))
    except Exception as exc:
        return _error(500, f"Gmail read failed: {exc}")
