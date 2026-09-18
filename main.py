"""Demo: read mail + calendar via Providers."""

from __future__ import annotations

import sys
from pathlib import Path

from integration_providers import Providers

ROOT = Path(__file__).resolve().parent


def _trunc(text: str, width: int = 80) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= width:
        return text
    return text[: width - 3] + "..."


def main() -> int:
    providers = Providers.discover(root=ROOT, allow_browser=True)
    if not providers.names:
        print(
            "No providers configured. Add credentials/credentials.json and/or credentials/icloud.json",
            file=sys.stderr,
        )
        return 1

    print(f"Loaded providers: {', '.join(providers.names)}")
    print()

    print("=== Emails ===")
    for i, item in enumerate(providers.read_emails(limit=5), start=1):
        print(
            f"{i:2}. [{item.provider}] {item.date}  "
            f"{_trunc(item.sender, 40)}  {_trunc(item.subject)}"
        )

    print()
    print("=== Calendar ===")
    for i, item in enumerate(providers.read_calendar(limit=10), start=1):
        print(f"{i:2}. [{item.provider}] {item.start}  {_trunc(item.summary)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
