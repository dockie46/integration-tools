"""iCloud credentials: Apple ID email + app-specific password."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class CredentialsMissingError(RuntimeError):
    """Raised when credentials/icloud.json is absent or incomplete."""


class ICloudAuthError(RuntimeError):
    """Raised when IMAP/CalDAV authentication or a request fails."""


@dataclass(frozen=True, slots=True)
class ICloudCredentials:
    email: str
    password: str
    # None = all calendars; otherwise display-name filters (case-insensitive).
    calendars: tuple[str, ...] | None = None


def load_credentials(path: Path) -> ICloudCredentials:
    if not path.exists():
        raise CredentialsMissingError(
            "iCloud credentials not found.\n"
            f"Expected file: {path}\n\n"
            "To fix this:\n"
            "  1. Go to https://appleid.apple.com → Sign-In and Security\n"
            "  2. Create an App-Specific Password\n"
            "  3. Save JSON as:\n"
            '     {"email": "you@icloud.com", "password": "xxxx-xxxx-xxxx-xxxx",'
            ' "calendars": ["Home", "Work"]}'
        )

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise CredentialsMissingError(f"Invalid JSON in {path}: {exc}") from exc

    email = (data.get("email") or "").strip()
    password = (data.get("password") or "").strip()
    if not email or not password:
        raise CredentialsMissingError(
            f"{path} must contain non-empty 'email' and 'password' fields."
        )

    raw_calendars = data.get("calendars")
    calendars: tuple[str, ...] | None
    if raw_calendars is None:
        calendars = None
    elif isinstance(raw_calendars, list):
        calendars = tuple(str(item).strip() for item in raw_calendars if str(item).strip())
        if not calendars:
            calendars = None
    else:
        raise CredentialsMissingError(f"{path}: 'calendars' must be a JSON array of names.")

    return ICloudCredentials(email=email, password=password, calendars=calendars)
