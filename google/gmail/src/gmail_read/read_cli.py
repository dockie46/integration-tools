"""Local Gmail reader: authenticate once in a browser, then list and read mail."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .auth import CredentialsMissingError, GmailAuthError
from .client import GmailClient
from .models import GmailMessage

DEFAULT_LIST_QUERY = "in:inbox"
DEFAULT_LIST_MAX = 20
# Relative to the process cwd — run from the integration-tools repo root.
DEFAULT_CREDENTIALS = "credentials/credentials.json"
DEFAULT_TOKEN = "token.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gmail-read",
        description="Read Gmail from a local client (desktop OAuth). Same client later runs on Lambda.",
    )
    parser.add_argument(
        "--credentials",
        default=DEFAULT_CREDENTIALS,
        help="Path to OAuth Desktop app credentials.json",
    )
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="Path to store/read the OAuth token")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="Sign in with Google in a browser and save token.json")

    list_parser = sub.add_parser("list", help="List matching messages (headers + snippet)")
    list_parser.add_argument(
        "--query", default=DEFAULT_LIST_QUERY, help=f"Gmail search query (default: {DEFAULT_LIST_QUERY!r})"
    )
    list_parser.add_argument(
        "--max", type=int, default=DEFAULT_LIST_MAX, dest="max_messages", help="Maximum messages to list"
    )
    list_parser.add_argument("--json", action="store_true", dest="as_json", help="Print JSON instead of a table")

    get_parser = sub.add_parser("get", help="Read one message, including the text body")
    get_parser.add_argument("message_id", help="Gmail message id from `gmail-read list`")
    get_parser.add_argument("--json", action="store_true", dest="as_json", help="Print JSON including html_body")
    get_parser.add_argument("--html", action="store_true", help="Print the HTML body instead of plain text")
    return parser


def _connect(args: argparse.Namespace, *, allow_browser: bool) -> GmailClient:
    credentials_path = Path(args.credentials).resolve()
    token_path = Path(args.token).resolve()
    return GmailClient.from_files(credentials_path, token_path, allow_browser=allow_browser)


def _print_list_row(message: GmailMessage) -> None:
    subject = message.subject.replace("\n", " ")
    if len(subject) > 80:
        subject = subject[:77] + "..."
    print(f"{message.message_id}  {message.date}  {message.sender}  {subject}")


def _print_message(message: GmailMessage, *, html: bool) -> None:
    print(f"Id: {message.message_id}")
    print(f"Thread: {message.thread_id}")
    print(f"Subject: {message.subject}")
    print(f"From: {message.sender}")
    print(f"To: {message.to}")
    print(f"Date: {message.date}")
    if message.label_ids:
        print(f"Labels: {', '.join(message.label_ids)}")
    if message.attachments:
        print("Attachments:")
        for attachment in message.attachments:
            size = f" {attachment.size} bytes" if attachment.size is not None else ""
            print(f"  - {attachment.filename} ({attachment.mime_type}{size})")
    print()
    if html:
        print(message.html_body or "(no HTML body)")
        return
    print(message.text_body or message.snippet or "(no text body)")


def run(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(line_buffering=True)
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "auth":
            print("Authenticating with Gmail...")
            _connect(args, allow_browser=True)
            print(f"Signed in. Token saved to {Path(args.token).resolve()}")
            print("For Lambda, store this token.json as the GOOGLE_TOKEN_JSON secret.")
            return 0

        client = _connect(args, allow_browser=True)

        if args.command == "list":
            messages = client.list_messages(args.query, args.max_messages, include_body=False)
            if args.as_json:
                print(json.dumps([m.to_dict() for m in messages], indent=2, ensure_ascii=False))
                return 0
            print(f"Query: {args.query}")
            print(f"Matching messages: {len(messages)}")
            for message in messages:
                _print_list_row(message)
            return 0

        if args.command == "get":
            message = client.get(args.message_id, include_body=True)
            if args.as_json:
                print(json.dumps(message.to_dict(), indent=2, ensure_ascii=False))
                return 0
            _print_message(message, html=args.html)
            return 0
    except (CredentialsMissingError, GmailAuthError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"unknown command {args.command!r}")
    return 2


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
